# -*- coding: utf-8 -*-
"""
Description: database models

Copyright (c) 2013—2014 Andrea Peltrin
Portions are copyright (c) 2013 Rui Carmo
License: MIT (see LICENSE for details)
"""

import pickle
from datetime import datetime, timedelta
from peewee import *
from playhouse.migrate import *
from playhouse.signals import Model as BaseModel, pre_save
from webob.exc import status_map

from utilities import *
import favicon
from coldsweat import config, logger


# Defer database init, see connect() below
engine = config.get('database', 'engine')
if engine == 'sqlite':
    _db = SqliteDatabase(None, threadlocals=True)
    migrator = SqliteMigrator(_db)
elif engine == 'mysql':
    _db = MySQLDatabase(None)
    migrator = MySQLMigrator(_db)
elif engine == 'postgresql':
    _db = PostgresqlDatabase(None, autorollback=True)
    migrator = PostgresqlMigrator(_db)
else:
    raise ValueError('Unknown database engine %s. Should be sqlite, postgresql or mysql' % engine)

# ------------------------------------------------------
# Custom fields
# ------------------------------------------------------

class PickleField(BlobField):
    def db_value(self, value):
        return super(PickleField, self).db_value(pickle.dumps(value, 2)) # Use newer protocol

    def python_value(self, value):
        return pickle.loads(value)

# ------------------------------------------------------
# Coldsweat models
# ------------------------------------------------------

class CustomModel(BaseModel):
    """
    Binds the database to all models
    """

    @classmethod
    def field_exists(klass, db_column):
        c = klass._meta.database.execute_sql('SELECT * FROM %s;' % klass._meta.db_table)
        return db_column in [d[0] for d in c.description]

    class Meta:
        database = _db


class User(CustomModel):
    """
    Coldsweat user
    """
    DEFAULT_CREDENTIALS = 'coldsweat', 'coldsweat'
    MIN_PASSWORD_LENGTH = 8

    username            = CharField(unique=True)
    password            = CharField()
    email               = CharField(null=True)
    api_key             = CharField(unique=True)
    is_enabled          = BooleanField(default=True)

    class Meta:
        db_table = 'users'

    #@@FIXME: we should use email instead as Fever API dictates
    @staticmethod
    def make_api_key(username, password):
        return make_md5_hash('%s:%s' % (username, password))

    @staticmethod
    def validate_credentials(username, password):
        try:
            user = User.get((User.username == username) &
                (User.password == password) &
                (User.is_enabled == True))
        except User.DoesNotExist:
            return None

        return user

    @staticmethod
    def validate_api_key(api_key):
        try:
            # Clients may send api_key in uppercase, lower() it
            user = User.get((User.api_key == api_key.lower()) &
                (User.is_enabled == True))
        except User.DoesNotExist:
            return None

        return user

    @staticmethod
    def validate_password(password):
        #@@TODO: Check for unacceptable chars
        return len(password) >= User.MIN_PASSWORD_LENGTH

@pre_save(sender=User)
def on_save_handler(model, user, created):
     user.api_key = User.make_api_key(user.username, user.password)


#@@REMOVEME: We keep this only to make migrations work
class Icon(CustomModel):
    """
    Feed (fav)icons, stored as data URIs
    """
    data                = TextField()

    class Meta:
        db_table = 'icons'


class Group(CustomModel):
    """
    Feed group/folder
    """
    DEFAULT_GROUP = 'Default'

    title               = CharField(unique=True)

    class Meta:
        order_by = ('title',)
        db_table = 'groups'


class Feed(CustomModel):
    """
    Atom/RSS feed
    """

    is_enabled           = BooleanField(default=True)        # Fetch feed?
    self_link            = CharField()                       # The URL of the feed itself (rel=self)
    error_count          = IntegerField(default=0)

    # Nullable

    title                = CharField(null=True)
    alternate_link       = CharField(null=True)              # The URL of the HTML page associated with the feed (rel=alternate)
    etag                 = CharField(null=True)              # HTTP E-tag
    last_updated_on      = DateTimeField(null=True)          # As UTC
    last_checked_on      = DateTimeField(null=True)          # As UTC
    last_status          = IntegerField(null=True)           # Last returned HTTP code

    icon                 = TextField(null=True)              # Stored as data URI
    icon_last_updated_on = DateTimeField(null=True)          # As UTC


    class Meta:
        indexes = (
            (('self_link',), True),
            (('last_checked_on',), False),
        )
        db_table = 'feeds'

    @property
    def last_updated_on_as_epoch(self):
        # Never updated?
        if self.last_updated_on:
            return datetime_as_epoch(self.last_updated_on)
        return 0

class Entry(CustomModel):
    """
    Atom/RSS entry
    """

    guid            = CharField()                               # 'id' in Atom parlance
    feed            = ForeignKeyField(Feed, on_delete='CASCADE')
    title           = TextField()
    content_type    = CharField(default='text/html')
    content         = TextField()
    #@@TODO: rename to published_on
    last_updated_on = DateTimeField()                           # As UTC

    # Nullable
    author          = CharField(null=True)
    link            = TextField(null=True)

    class Meta:
        indexes = (
            (('guid',), False),
            (('link',), False),
        )
        db_table = 'entries'

    @property
    def last_updated_on_as_epoch(self):
        return datetime_as_epoch(self.last_updated_on)


class Saved(CustomModel):
    """
    Entries 'saved' status
    """
    user            = ForeignKeyField(User)
    entry           = ForeignKeyField(Entry, on_delete='CASCADE')
    saved_on        = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (('user', 'entry'), True),
        )


class Read(CustomModel):
    """
    Entries 'read' status
    """
    user           = ForeignKeyField(User)
    entry          = ForeignKeyField(Entry, on_delete='CASCADE')
    read_on        = DateTimeField(default=datetime.utcnow)

    class Meta:
        indexes = (
            (('user', 'entry'), True),
        )


class Subscription(CustomModel):
    """
    A user's feed subscription
    """
    user           = ForeignKeyField(User)
    group          = ForeignKeyField(Group, on_delete='CASCADE')
    feed           = ForeignKeyField(Feed, on_delete='CASCADE')

    class Meta:
        indexes = (
            (('user', 'group', 'feed'), True),
        )
        db_table = 'subscriptions'


class Session(CustomModel):
    """
    Web session
    """
    key             = CharField()
    value           = PickleField()
    expires_on      = DateTimeField()

    class Meta:
        indexes = (
            (('key', ), True),
        )
        db_table = 'sessions'


# ------------------------------------------------------
# Utility functions
# ------------------------------------------------------

def _init_sqlite():
    filename = config.get('database', 'filename')
    _db.init(filename)

def _init_mysql():
    database = config.get('database', 'database')
    kwargs = dict(
        host        = config.get('database', 'hostname'),
        user        = config.get('database', 'username'),
        passwd      = config.get('database', 'password')
    )
    _db.init(database, **kwargs)

def _init_postgresql():
    database = config.get('database', 'database')
    kwargs = dict(
        host        = config.get('database', 'hostname'),
        user        = config.get('database', 'username'),
        password    = config.get('database', 'password')
    )
    _db.init(database, **kwargs)

def connect():
    """
    Shortcut to init and connect to database
    """

    engines = {
        'sqlite'    : _init_sqlite,
        'mysql'     : _init_mysql,
        'postgresql': _init_postgresql,
    }
    engines[engine]()
    _db.connect()

def transaction():
    return _db.transaction()

def close():
    try:
        # Attempt to close database connection
        _db.close()
    except ProgrammingError, exc:
        logger.error('caught exception while closing database connection: %s' % exc)


def migrate_database_schema():
    '''
    Migrate database schema from previous versions (0.9.4 and up)
    '''
    drop_table_migrations, column_migrations = [], []

    # Version 0.9.4 --------------------------------------------------------------

    # Change columns

    if Feed.field_exists('icon_id') and engine != 'sqlite':
        column_migrations.append(migrator.drop_column('feeds', 'icon_id'))

    if not Feed.field_exists('icon'):
        column_migrations.append(migrator.add_column('feeds', 'icon', Feed.icon))

    if not Feed.field_exists('icon_last_updated_on'):
        column_migrations.append(migrator.add_column('feeds', 'icon_last_updated_on', Feed.icon_last_updated_on))

    if not Entry.field_exists('content_type'):
        column_migrations.append(migrator.add_column('entries', 'content_type', Entry.content_type))

    # Drop tables

    if Icon.table_exists():
        drop_table_migrations.append(Icon.drop_table)

    # ----------------------------------------------------------------------------

    # Run all table and column migrations

    if column_migrations:
        # Let caller to catch any OperationalError's
        migrate(*column_migrations)

    for drop in drop_table_migrations:
        drop()

    # True if at least one is non-empty
    return drop_table_migrations or column_migrations


def setup():
    """
    Create database and tables for all models and setup bootstrap data
    """

    models = User, Feed, Entry, Group, Read, Saved, Subscription, Session

    # WAL mode is persistent, so we can to setup
    #   it once - see http://www.sqlite.org/wal.html
    if engine == 'sqlite':
        _db.execute_sql('PRAGMA journal_mode=WAL')

    for model in models:
        model.create_table(fail_silently=True)

    # Create the bare minimum to boostrap system
    with transaction():

        # Avoid duplicated default group
        try:
            Group.create(title=Group.DEFAULT_GROUP)
        except IntegrityError:
            return

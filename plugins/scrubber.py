# -*- coding: utf-8 -*-
'''
Description: Scrubber plugin. Remove links and images from 
  feed entries according to etc/blacklist

Copyright (c) 2013—2014 Andrea Peltrin
License: MIT (see LICENSE for details)
'''

from os import path

from coldsweat import *
from coldsweat.markup import html

DOMAINS = []    

@event('fetch_started')
def fetcher_started():
    if DOMAINS: return # Already initialized
    
    backlist_path = path.join(installation_dir, 'etc/blacklist')
    try:
        with open(backlist_path) as f:
            for line in f:
                if line == '\n' or line.startswith('#') or line.startswith(';'):
                    continue # Skip empty values and comments                
                DOMAINS.append(line.rstrip('\n'))    
    except IOError:
        logger.warn("could not load %s" % backlist_path)    
        return    

    logger.debug("loaded blacklist: %s" % ', '.join(DOMAINS))
    
    
@event('entry_parsed')
def entry_parsed(entry, parsed_entry):
    if DOMAINS and ('html' in entry.content_type):
        entry.content = html.scrub_html(entry.content, DOMAINS)    
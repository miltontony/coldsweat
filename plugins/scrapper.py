import unicodedata

from fuzzywuzzy import fuzz
from coldsweat import event, logger


def get_positive_words(url):
    if url.startswith('http://www.news24.com'):
        return ['article', 'col626']
    return None


def clean(t):
    return unicodedata.normalize('NFKD', unicode(t)).encode('ascii', 'ignore')


def get_unicode(txt):
    if not txt:
        return ''
    try:
        txt = unicode(txt, errors="ignore")
    except:
        pass
    try:
        txt = txt.encode('ascii', 'ignore')
    except:
        pass
    return str(txt)


def scrape(url):
    from goose import Goose
    from readability.readability import Document
    import urllib2
    ua = ('Mozilla/5.0 (X11; Linux i686) AppleWebKit/537.36 (KHTML, '
          'like Gecko) Chrome/33.0.1750.152 Safari/537.36')
    req = urllib2.Request(url, headers={
        'User-Agent': ua,
        'Accept-Encoding': 'identity',
    })
    page = unicode(urllib2.urlopen(req).read(), errors='ignore')

    pos = get_positive_words(url)
    if pos:
        html = Document(page, positive_keywords=pos).summary()
    else:
        html = Document(page).summary()
    return clean(Goose().extract(raw_html=html).cleaned_text)


def update_fulltext(entry):
    fulltext = scrape(entry.link)

    if fulltext:
        ratio = fuzz.token_set_ratio(
            get_unicode(entry.content),
            get_unicode(fulltext))
        if ratio >= 80:
            entry.fulltext = fulltext
            logger.info('Scraped: %s' % entry.link)
        else:
            logger.warning(
                'Fulltext for %s does not meet similarity ratio: %s' %
                (entry.link, ratio))


@event('entry_parsed')
def entry_parsed(entry, parsed_entry):
    try:
        update_fulltext(entry)
    except:
        logger.error('Error while scrapping: %s' % entry.link, exc_info=True)

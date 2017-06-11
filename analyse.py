#!/usr/bin/python
"""Hugo content analyser.

Usage:
  analyse flickr list [--comment]
  analyse flickr shorten [--force]
  analyse images name [--dump]
  analyse images download
  analyse shortcode list
  analyse (-h | --help)
  analyse --version

Options:
  -h --help     Show this screen.
  --version     Show version.
  --force       Force

"""
from bs4 import BeautifulSoup
from docopt import docopt
import collections
import fnmatch
import os
import re
import shutil
import string
import urllib3
import yaml


ContentDir = "content"


HTTP = urllib3.PoolManager(retries=32)
FlickrLongPattern = re.compile("https://www.flickr.com/[a-zA-Z0-9/_%@.-]*")
FlickrShortPattern = re.compile("flic.kr/p/[a-zA-Z0-9]*")


Illustration = collections.namedtuple('Illustration', 'name source')
Shortcode = collections.namedtuple('Shortcode', 'name parameters')


def list_items(directory, pattern="*.md"):
    for root, dirs, files in os.walk(directory):
        for f in files:
            if fnmatch.fnmatch(f, pattern):
                yield (f, os.path.join(root, f))


def nameof(filename):
    return os.path.splitext(filename)[0]


def extensionof(filename):
    return os.path.splitext(filename)[1]


def ensure_directory(path):
    try:
        os.makedirs(path)
    except OSError:
        pass


def read_file(path):
    with open(path, 'r') as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(str(content))


def write_file_binary(path, content):
    with open(path, "wb") as f:
        f.write(content)


def compute_flickr_short_url(identifier):
    table = '123456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ'
    encoding=''
    while identifier >= len(table):
        div,mod = divmod(identifier, len(table))
        encoding = table[mod] + encoding
        identifier = int(div)
    encoding = table[identifier] + encoding
    return "http://flic.kr/p/%s" % encoding


def get_flickr_image_title(url):
    def meta(tag):
        return tag.name == 'meta' and 'name' in tag.attrs and tag['name'] == 'title'

    html = HTTP.request('GET', url + '/sizes/o/')
    title =  BeautifulSoup(html.data, 'html5lib').find(meta)['content'].split('|')[0]
    return title.lower()


def flick_download_image(url):
    html = HTTP.request('GET', url + '/sizes/o/')
    image_url = re.findall(r'https:[^" \\:]*_o\.jpg', html.data.decode('utf-8'))
    if image_url:
        return HTTP.request('GET', image_url[0]).data
    else:
        return None


def check_flickr_short_url(url, expected_pseudo, expected_image_identifier):
    try:
        html = HTTP.request('GET', url + '/sizes/o/')
        url_sq = re.findall(r'href="/photos/([^"]*)', html.data.decode('utf-8'))[2]
        pseudo, image = url_sq.split('/')[0:2]
        return expected_pseudo == pseudo and expected_image_identifier == long(image)
    except :
        return False


def flickr_shorten(force):
    def pseudo_of(url):
        return url.split('/')[4]
    def image_identifier_of(url):
        return long(url.split('/')[5])

    for name, path in list_items(ContentDir):
        content = read_file(path)
        for url in FlickrLongPattern.findall(content):
            short = compute_flickr_short_url(image_identifier_of(url))
            if force or check_flickr_short_url(short, pseudo_of(url), image_identifier_of(url)):
                print "%-20s: %s" % (short, url)
                content = content.replace(url, short)
                write_file(path, content)
            else:
                print "Warning: check failed for %s (%s)" % (url, short)


def flickr_list(comment):
    long_urls_count = 0
    short_urls_count = 0
    for name, path in list_items(ContentDir):
        content = read_file(path)
        long_urls = FlickrLongPattern.findall(content)
        short_urls = FlickrShortPattern.findall(content)
        if len(long_urls) > 0 or len(short_urls) > 0:
            print("\nFile %s:" % path)
            if comment:
                for url in long_urls + short_urls:
                    print("\t%50s %30s" % (url, get_flickr_image_title(url)))
            else:
                for url in long_urls + short_urls:
                    print("\t%50s" % (url))
        long_urls_count += len(long_urls)
        short_urls_count += len(short_urls)
    print("\nStatistics:")
    print("\tLong URL count: %d" % long_urls_count)
    print("\tShort URL count: %d" % short_urls_count)


def images_download():
    def is_flick_source(url):
        if url:
            return ("://flick" in url) or ("flic.kr/" in url)
        else:
            return False
    for name, path in list_items(ContentDir):
        for illustration in illustrations_from(read_file(path)):
            if is_flick_source(illustration.source):
                image_path = os.path.join(os.path.dirname(path), illustration.name) + ".jpg"
                print image_path
                if os.path.exists(image_path):
                    print("\t%50s: %30s: cached" % (illustration.source, illustration.name))
                    continue
                image = flick_download_image(illustration.source)
                if image:
                    print("\t%50s: %30s: downloaded" % (illustration.source, illustration.name))
                    write_file_binary(image_path, image)


def is_semantic_name(name):
    if sum(c.isdigit() for c in name) > 4:
        return (False, 'Too many digits')
    if sum(c.isupper() for c in name):
        return (False, 'Contains uppercase')
    return (True, 'OK')


def shortcodes_of(content):
    return re.compile('{{<(.*)>}}').findall(content)


def parse_shortcode(shortcode):
    def parse_parameter(parameter):
        name, value = parameter.split("=", 1)
        return name.strip(), value[1:-1].strip()
    NamePattern = re.compile('[a-zA-Z]+="[^"]*"')
    name = shortcode.strip().split(' ')[0]
    return Shortcode(name=name, parameters=dict([parse_parameter(p) for p in NamePattern.findall(shortcode)]))


def read_front_matter(content):
    return yaml.load_all(content).next()


def illustrations_from(content):
    illustrations = []
    front_matter = read_front_matter(content)
    if 'illustration' in front_matter:
        illustrations.append(
            Illustration(
                name=front_matter['illustration']['name'],
                source=front_matter['illustration'].get('source', '')))
    for shortcode in (parse_shortcode(s) for s in shortcodes_of(content)):
        if shortcode.name in ["img", 'img-large']:
            illustrations.append(
                Illustration(
                    name=shortcode.parameters['name'],
                    source=shortcode.parameters.get('source', '')))
    return illustrations


def images_name(dump):
    images = []
    for name, path in list_items(ContentDir):
        for illustration in illustrations_from(read_file(path)):
            status, reason = is_semantic_name(illustration.name)
            if not status:
                images.append({
                    "name": illustration.name,
                    "new_name": '',
                    "reason": reason,
                    "where": path
                })
                print "Bad  : %-30s (%s): %s" % (illustration.name, path, reason)
    if dump:
        with file('image-rename.yaml', 'w') as f:
            yaml.dump(images, f, default_flow_style=False)


def shortcode_list():
    for name, path in list_items(ContentDir):
        for shortcode in shortcodes_of(read_file(path)):
            print "%-20s: %s" % (shortcode, path)


if __name__ == '__main__':
    arguments = docopt(__doc__, version='Hugo analyse 1.0')
    if arguments['flickr']:
        if arguments['list']:
            flickr_list(comment=arguments['--comment'])
        elif arguments['shorten']:
            flickr_shorten(force=arguments['--force'])
    elif arguments['images']:
        if arguments['name']:
            images_name(dump=arguments['--dump'])
        elif arguments['download']:
            images_download()
    elif arguments['shortcode']:
        if arguments['list']:
            shortcode_list()


# TODO:
#- batch rename images
#- batch download flick images

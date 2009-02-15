#!/usr/bin/env python

import urllib2
import gzip
import zipfile
import sys
import cPickle
import re
import os
from StringIO import StringIO
from optparse import OptionParser

from BeautifulSoup import BeautifulSoup, BeautifulStoneSoup

__author__ = 'David Lynch (kemayo at gmail dot com)'
__version__ = '0.1'
__copyright__ = 'Copyright (c) 2009 David Lynch'
__license__ = 'New BSD License'

"""
So, wowace.com projects have an RSS feed. OKAY!

This script may be run like so:
    ./waup.py install <projectname>, <projectname>, ...
    ./waup.py update [<projectname>, <projectname>, ...]

It doesn't do anything fancy. It just downloads the files and installs them.
"""

USER_AGENT = 'waup/%s' % __version__
PROJECT_URL = 'http://www.wowace.com/projects/%s/files.rss'

WOW_DIRECTORY = '/home/david/.wine/drive_c/Program Files/World of Warcraft/Interface/AddOns'

CACHE = False

class UnknownProjectException(Exception):
    pass

def load_project(project_name):
    try:
        rss = _fetch(PROJECT_URL % project_name)
    except urllib2.HTTPError:
        raise UnknownProjectException, "Project %s not found." % project_name
    soup = BeautifulStoneSoup(rss)
    latest = soup.find('item')
    return {
        'project': project_name,
        'file_url': get_file_url_from_filepage(latest.find('link').string),
        'guid': str(latest.find('guid').string), # str() because .string is actually a NavigableString, which is *huge*
    }

def get_file_url_from_filepage(filepage_url):
    """Really, this just returns the first href that ends in .zip. So it may break."""
    html = _fetch(filepage_url)
    soup = BeautifulSoup(html)
    return soup.find('a', href=re.compile(r'\.zip$'))['href']

def install_addon(name, force = False, clean = False):
    """Installs the latest version of an addon to your addons directory, based on its wowace project name."""
    project = load_project(name)
    cached_project = CACHE['addons'].get(name)
    if (not force) and cached_project and cached_project.get('guid') == project.get('guid'):
        print("Skipping %s; latest version already installed." % name)
        return True
    zip = zipfile.ZipFile(_fetch(project['file_url']))
    project['install_dir'] = re.search(r'^([^/]+)/', zip.filelist[0].filename).group(1)
    
    install_to = os.path.join(WOW_DIRECTORY, project['install_dir'])
    if clean and os.path.exists(install_to):
        _removedir(install_to)

    _unzip(zip, WOW_DIRECTORY)
    zip.close()
    
    print("%s now installed at %s" % (name, project['guid']))

    CACHE['addons'][name] = project

def uninstall_addon(name):
    project = CACHE['addons'].get(name)
    if not project:
        print("Couldn't uninstall %s; not installed.")
        return
    if os.path.exists(os.path.join(WOW_DIRECTORY, project['install_dir'])):
        _removedir(os.path.join(WOW_DIRECTORY, project['install_dir']))
    else:
        print("Couldn't delete install directory; %s not found." % project['install_dir'])
    
    print("%s uninstalled" % name)

    return True

def blank_cache():
    return {
        'addons': {},
    }

def load_cache():
    if os.path.exists(os.path.join(WOW_DIRECTORY, 'waup_cache.pkl')):
        try:
            pickled_versions = open(os.path.join(WOW_DIRECTORY, 'waup_cache.pkl'), 'rb')
            cache = cPickle.load(pickled_versions)
            pickled_versions.close()
            # We managed to load the list of addons.  Now, let's check to see whether any have been uninstalled...
            for project, info in cache.get('addons').items():
                if not (info.get('install_dir') and os.path.isdir(os.path.join(WOW_DIRECTORY, info['install_dir']))):
                    # Addon directory is gone. Mark as uninstalled.
                    del(cache['addons'][project])
                    print("Couldn't find %s, removing from list of installed projects." % project)
        except EOFError:
            cache = blank_cache()
    else:
        cache = blank_cache()
    return cache

def save_cache(cache):
    pickled_versions = open(os.path.join(WOW_DIRECTORY, 'waup_cache.pkl'), 'wb')
    cPickle.dump(cache, pickled_versions)
    pickled_versions.close()

# A few utility functions:

def _unzip(zip, path):
    """Takes a ZipFile and extracts it into path"""
    for f in zip.namelist():
        if not f.endswith('/'):
            root, name = os.path.split(f)
            directory = os.path.normpath(os.path.join(path, root))
            if not os.path.isdir(directory):
                os.makedirs(directory)
            
            dest = os.path.join(directory, name)
            
            nf = file(dest, 'wb')
            nf.write(zip.read(f))
            nf.close()
            permissions = _permissions_from_external_attr(zip.getinfo(f).external_attr)
            if permissions == 0:
                permissions = 0644
            os.chmod(dest, permissions)

def _permissions_from_external_attr(l):
    """Creates a permission mask from the external_attr field of a zipfile.ZipInfo object, suitable for passing to os.chmod
    From my own somewhat limited investigation, bits 17-25 of the external_attr field are a *reversed* permissions bitmask
    e.g. bit 17 is the group execute bit, bit 18 is the group write bit, etc.
    """
    p = []
    for i in range(24,15,-1):
        # I'm awful at remembering how bitwise operations work.  So, for my own reference in the future:
        # Shifts the value of l 'i' bits to the right (i.e. divides it by 2**i), and checks whether the first bit is 1 or 0.
        p.append((l >> i) & 1)
    # This would produce the standard octal string for permissions (e.g. 0755, which is rwxr-wr-w)
    #return str((p[0]+p[1]*2+p[2]*4))+str((p[3]+p[4]*2+p[5]*4))+str((p[6]+p[7]*2+p[8]*4))
    # This produces an integer, suitable for passing to os.chmod (i.e., for 0755: 493)
    return int(''.join([str(i) for i in p]), 2)

def _fetch(url):
    """A generic URL-fetcher, which handles gzipped content, returns a file-like object"""
    request = urllib2.Request(url)
    request.add_header('Accept-encoding', 'gzip')
    request.add_header('User-agent', USER_AGENT)
    f = urllib2.urlopen(request)
    data = StringIO(f.read())
    f.close()
    if f.headers.get('content-encoding', '') == 'gzip':
        data = gzip.GzipFile(fileobj=data)
    return data

def _rmgeneric(path, __func__):
    try:
        __func__(path)
    except OSError, (errno, strerror):
        print "Error removing %(path)s, %(error)s " % {'path' : path, 'error': strerror }

def _removedir(path):
    if not os.path.isdir(path):
        return
    
    for x in os.listdir(path):
        fullpath=os.path.join(path, x)
        if os.path.isfile(fullpath):
            _rmgeneric(fullpath, os.remove)
        elif os.path.isdir(fullpath):
            _removedir(fullpath)
    _rmgeneric(path, os.rmdir)

def _dispatch():
    # get_deps = True, unpackage = False, delete_old = True, force = False
    parser = OptionParser(version="%%prog %s" % __version__, usage = "usage: %prog [options] ([addon1] ... [addon99])")
    parser.add_option('-c', '--clean', action='store_true', dest='clean', default=False,
        help="Delete addon directories before replacing them")
    parser.add_option('-f', '--force', action='store_true', dest='force', default=False,
        help="Redownload all addons, even if current")
    parser.add_option('-r', '--remove', action='store_true', dest='remove', default=False,
        help="Remove addons passed as arguments")
    options, args = parser.parse_args(sys.argv[1:])
    
    if args:
        if options.remove:
            for project in args:
                uninstall_addon(project)
        else:
            for project in args:
                install_addon(project, options.force, options.clean)
    else:
        if options.remove:
            print("No project names provided.")
            return
        for project in CACHE['addons']:
            install_addon(project, options.force, options.clean)

if __name__ == "__main__":
    CACHE = load_cache()
    
    _dispatch()
    
    save_cache(CACHE)

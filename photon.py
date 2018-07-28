#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Let's import what we need
import os
import sys
import time
import shutil
import random
import warnings
import argparse
import threading
from re import search, findall
from requests import get, post

try:
    from urllib.parse import urlparse # for python3
except ImportError:
    input = raw_input
    from urlparse import urlparse # for python2
from plugins.exporter import exporter
from plugins.dnsdumpster import dnsdumpster

colors = True # Output should be colored
machine = sys.platform # Detecting the os of current system
if machine.startswith('os') or machine.startswith('win') or machine.startswith('darwin') or machine.startswith('ios'):
    colors = False # Colors shouldn't be displayed in mac & windows
if not colors:
    end = red = white = green = yellow = run = bad = good = info = que =  '' 
else:
    end = '\033[1;m'
    red = '\033[91m'
    white = '\033[1;97m'
    green = '\033[1;32m'
    yellow = '\033[1;33m'
    run = '\033[1;97m[~]\033[1;m'
    bad = '\033[1;31m[-]\033[1;m'
    good = '\033[1;32m[+]\033[1;m'
    info = '\033[1;33m[!]\033[1;m'
    que =  '\033[1;34m[?]\033[1;m'

# Just a fancy ass banner
print ('''%s      ____  __          __            
     / %s__%s \/ /_  ____  / /_____  ____ 
    / %s/_/%s / __ \/ %s__%s \/ __/ %s__%s \/ __ \\
   / ____/ / / / %s/_/%s / /_/ %s/_/%s / / / /
  /_/   /_/ /_/\____/\__/\____/_/ /_/ %s\n''' %
  (red, white, red, white, red, white, red, white, red, white, red, white, red, end))

warnings.filterwarnings('ignore') # Disable SSL related warnings

# Processing command line arguments
parser = argparse.ArgumentParser()
# Options
parser.add_argument('-u', '--url', help='root url', dest='root')
parser.add_argument('-c', '--cookie', help='cookie', dest='cook')
parser.add_argument('-r', '--regex', help='regex pattern', dest='regex')
parser.add_argument('-e', '--export', help='export format', dest='export')
parser.add_argument('-o', '--output', help='output directory. defaults to `output/<domain name>`', dest='output')
parser.add_argument('-s', '--seeds', help='additional seed urls', dest='seeds')
parser.add_argument('--user-agent', help='custom user agent(s)', dest='user_agent')
parser.add_argument('-l', '--level', help='levels to crawl', dest='level', type=int)
parser.add_argument('--timeout', help='http request timeout', dest='timeout', type=float)
parser.add_argument('-t', '--threads', help='number of threads', dest='threads', type=int)
parser.add_argument('-d', '--delay', help='delay between requests', dest='delay', type=float)
# Switches
parser.add_argument('--dns', help='dump dns data', dest='dns', action='store_true')
parser.add_argument('--ninja', help='ninja mode', dest='ninja', action='store_true')
parser.add_argument('--update', help='update photon', dest='update', action='store_true')
parser.add_argument('--only-urls', help='only extract urls', dest='only_urls', action='store_true')
args = parser.parse_args()

####
# This function git clones the latest version and merges it with the current directory
####

def update():
    print('%s Checking for updates' % run)
    changes = '''ability to specify output directory & user agent;bigger & seperate file for user-agents''' # Changes must be seperated by ;
    latest_commit = get('https://raw.githubusercontent.com/s0md3v/Photon/master/photon.py').text

    if changes not in latest_commit: # just hack to see if a new version is available
        changelog = search(r"changes = '''(.*?)'''", latest_commit)
        changelog = changelog.group(1).split(';') # splitting the changes to form a list
        print ('%s A new version of Photon is available.' % good)
        print ('%s Changes:' % info)
        for change in changelog: # print changes
            print ('%s>%s %s' % (green, end, change))

        current_path = os.getcwd().split('/') # if you know it, you know it
        folder = current_path[-1] # current directory name
        path = '/'.join(current_path) # current directory path
        choice = input('%s Would you like to update? [Y/n] ' % que).lower()

        if choice != 'n':
            print ('%s Updating Photon' % run)
            os.system('git clone --quiet https://github.com/s0md3v/Photon %s' % (folder))
            os.system('cp -r %s/%s/* %s && rm -r %s/%s/ 2>/dev/null' % (path, folder, path, path, folder))
            print ('%s Update successful!' % good)
    else:
        print ('%s Photon is up to date!' % good)

if args.update: # if the user has supplied --update argument
    update()
    quit() # quitting because files have been changed

if args.root: # if the user has supplied a url
    main_inp = args.root
    if main_inp.endswith('/'): # if the url ends with '/'
        main_inp = main_inp[:-1] # we will remove it as it can cause problems later in the code
else: # if the user hasn't supplied a url
    print ('\n' + parser.format_help().lower())
    quit()

delay = 0 # Delay between requests
timeout = 6 # HTTP request timeout
cook = None # Cookie
ninja = False # Ninja mode toggle
crawl_level = 2 # Crawling level
thread_count = 2 # Number of threads
only_urls = False # only urls mode is off by default

if args.ninja:
    ninja = True
if args.only_urls:
    only_urls = True
if args.cook:
    cook = args.cook
if args.delay:
    delay = args.delay
if args.timeout:
    timeout = args.timeout
if args.level:
    crawl_level = args.level
if args.threads:
    thread_count = args.threads

# Variables we are gonna use later to store stuff
files = set() # pdf, css, png etc.
intel = set() # emails, website accounts, aws buckets etc.
robots = set() # entries of robots.txt
custom = set() # string extracted by custom regex pattern
failed = set() # urls that photon failed to crawl
storage = set() # urls that belong to the target i.e. in-scope
scripts = set() # javascript files
external = set() # urls that don't belong to the target i.e. out-of-scope
fuzzable = set() # urls that have get params in them e.g. example.com/page.php?id=2
endpoints = set() # urls found from javascript files
processed = set() # urls that have been crawled

everything = []
bad_intel = set() # unclean intel urls
bad_scripts = set() # unclean javascript file urls

seeds = []
if args.seeds: # if the user has supplied custom seeds
    seeds = args.seeds
    for seed in seeds.split(','): # we will convert them into a list
        storage.add(seed) # and them to storage for crawling

# If the user hasn't supplied the root url with http(s), we will handle it
if main_inp.startswith('http'):
    main_url = main_inp
else:
    try:
        get('https://' + main_inp)
        main_url = 'https://' + main_inp
    except:
        main_url = 'http://' + main_inp

storage.add(main_url) # adding the root url to storage for crawling

domain_name = urlparse(main_url).netloc # Extracts domain out of the url

# prepare output dirs
if args.output:
    output_dir = args.output
else:
    # default output dir
    output_dir = 'output/%s' % domain_name

if os.path.exists(output_dir): # if the directory already exists
    shutil.rmtree(output_dir, ignore_errors=True) # delete it, recursively
os.makedirs(output_dir) # create output directory

####
# This function makes requests to webpage and returns response body
####

if args.user_agent:
    user_agents = args.user_agent.split(',')
else:
    user_agents = []
    with open(os.getcwd() + '/core/user-agents.txt', 'r') as uas:
        for agent in uas:
            user_agents.append(agent.strip('\n'))

def requester(url):
    processed.add(url) # mark the url as crawled
    time.sleep(delay) # pause/sleep the program for specified time
    def normal(url):
        headers = {
        'Host' : domain_name, # ummm this is the hostname?
        'User-Agent' : random.choice(user_agents), # selecting a random user-agent
        'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language' : 'en-US,en;q=0.5',
        'Accept-Encoding' : 'gzip',
        'DNT' : '1',
        'Connection' : 'close'}
        # make request and return response
        try:
            response = get(url, cookies=cook, headers=headers, verify=False, timeout=timeout, stream=True)
            if 'text/html' in response.headers['content-type']:
                if response.status_code != '404':
                    return response.text
                else:
                    response.close()
                    failed.append(url)
                    return 'dummy'
            else:
                response.close()
                return 'dummy'
        except:
            return 'dummy'

    # pixlr.com API
    def pixlr(url):
        if url == main_url:
            url = main_url + '/' # because pixlr throws error if http://example.com is used
        # make request and return response
        return get('https://pixlr.com/proxy/?url=' + url, headers={'Accept-Encoding' : 'gzip'}, verify=False).text

    # codebeautify.org API
    def code_beautify(url):
        headers = {
        'User-Agent' : 'Mozilla/5.0 (X11; Linux x86_64; rv:61.0) Gecko/20100101 Firefox/61.0',
        'Accept' : 'text/plain, */*; q=0.01',
        'Accept-Encoding' : 'gzip',
        'Content-Type' : 'application/x-www-form-urlencoded; charset=UTF-8',
        'Origin' : 'https://codebeautify.org',
        'Connection' : 'close'
        }
        # make request and return response
        return post('https://codebeautify.com/URLService', headers=headers, data='path=' + url, verify=False).text

    # www.photopea.com API
    def photopea(url):
        # make request and return response
        return get('https://www.photopea.com/mirror.php?url=' + url, verify=False).text

    if ninja: # if the ninja mode is enabled
        # select a random request function i.e. random API
        response = random.choice([photopea, normal, pixlr, code_beautify])(url)
        if response != '':
            return response  # return response body
        else:
            return 'dummy'
    else:
        return normal(url)

####
# This function extracts links from robots.txt and sitemap.xml
####

def zap(url):
    response = get(url + '/robots.txt').text # makes request to robots.txt
    if '<body' not in response: # making sure robots.txt isn't some fancy 404 page
        matches = findall(r'Allow: (.*)|Disallow: (.*)', response) # If you know it, you know it
        if matches:
            for match in matches: # iterating over the matches, match is a tuple here
                match = ''.join(match) # one item in match will always be empty so will combine both items
                if '*' not in match: # if the url doesn't use a wildcard
                    url = main_url + match
                    storage.add(url) # add the url to storage list for crawling
                    robots.add(url) # add the url to robots list
            print ('%s URLs retrieved from robots.txt: %s' % (good, len(robots)))        
    response = get(url + '/sitemap.xml').text # makes request to sitemap.xml        
    if '<body' not in response: # making sure robots.txt isn't some fancy 404 page
        matches = findall(r'<loc>[^<]*</loc>', response) # regex for extracting urls
        if matches: # if there are any matches
            print ('%s URLs retrieved from sitemap.xml: %s' % (good, len(matches)))
            for match in matches:
                storage.add(match.split('<loc>')[1][:-6]) #cleaning up the url & adding it to the storage list for crawling

####
# This functions checks whether a url should be crawled or not
####

def is_link(url):
    # file extension that don't need to be crawled and are files
    conclusion = False # whether the the url should be crawled or not
    
    if url not in processed: # if the url hasn't been crawled already
        if not ('.xml' or '.png' or '.bmp' or '.jpg' or '.jpeg' or '.pdf' or '.css' or '.ico' or '.js' or '.svg' or '.json') in url:
            return True # url can be crawled
        else:
            files.add(url)
    return conclusion # return the conclusion :D

####
# This function extracts string based on regex pattern supplied by user
####

supress_regex = False
def regxy(pattern, response):
    try:
        matches = findall(r'%s' % pattern, response)
        for match in matches:
            custom.add(match)
    except:
        supress_regex = True

####
# This function extracts intel from the response body
####

def intel_extractor(response):
    matches = findall(r'''([\w\.-]+s[\w\.-]+\.amazonaws\.com)|(github\.com/[\w\.-/]+)|
    (facebook\.com/.*?)[\'" ]|(youtube\.com/.*?)[\'" ]|(linkedin\.com/.*?)[\'" ]|
    (twitter\.com/.*?)[\'" ]|([\w\.-]+@[\w\.-]+\.[\.\w]+)''', response)
    if matches:
        for match in matches: # iterate over the matches
            bad_intel.add(match) # add it to intel list

####
# This function extracts js files from the response body
####

def js_extractor(response):
    matches = findall(r'src=[\'"](.*?\.js)["\']', response) # extract .js files
    for match in matches: # iterate over the matches
        bad_scripts.add(match)

####
# This function extracts stuff from the response body
####

def extractor(url):
    response = requester(url) # make request to the url
    matches = findall(r'<[aA].*[href|HREF]=["\']{0,1}([^>"\']*)', response)
    for link in matches: # iterate over the matches
        link = link.split('#')[0] # remove everything after a "#" to deal with in-page anchors
        if is_link(link): # checks if the urls should be crawled
            if link.startswith('http') or link.startswith('//'):
                if link.startswith(main_url):
                    storage.add(link)
                else:
                    external.add(link)
            elif link.startswith('/'):
                storage.add(main_url + link)
            else:
                storage.add(main_url + '/' + link)
    if not only_urls:
        intel_extractor(response)
        js_extractor(response)
    if args.regex and not supress_regex:
        regxy(args.regex, response)

####
# This function extracts endpoints from JavaScript Code
####

def jscanner(url):
    response = requester(url) # make request to the url
    matches = findall(r'[\'"](/.*?)[\'"]|[\'"](http.*?)[\'"]', response) # extract urls/endpoints
    for match in matches: # iterate over the matches, match is a tuple
        match = match[0] + match[1] # combining the items because one of them is always empty
        if not search(r'[}{><"\']', match) and not match == '/': # making sure it's not some js code
            endpoints.add(match) # add it to the endpoints list

####
# This function starts multiple threads for a function
####

def threader(function, *urls):
    threads = [] # list of threads
    urls = urls[0] # because urls is a tuple
    for url in urls: # iterating over urls
        task = threading.Thread(target=function, args=(url,))
        threads.append(task)
    # start threads
    for thread in threads:
        thread.start()
    # wait for all threads to complete their work
    for thread in threads:
        thread.join()
    # delete threads
    del threads[:]

####
# This function processes the urls and sends them to "threader" function
####

def flash(function, links): # This shit is NOT complicated, please enjoy
    links = list(links) # convert links (set) to list
    for begin in range(0, len(links), thread_count): # range with step
        end = begin + thread_count
        splitted = links[begin:end]
        threader(function, splitted)
        progress = end
        if progress > len(links): # fix if overflow
            progress = len(links)
        sys.stdout.write('\r%s Progress: %i/%i' % (info, progress, len(links)))
        sys.stdout.flush()
    print ('')

then = time.time() # records the time at which crawling started

# Step 1. Extract urls from robots.txt & sitemap.xml
zap(main_url)

# Step 2. Crawl recursively to the limit specified in "crawl_level"
for level in range(crawl_level):
    links = storage - processed # links to crawl = all links - already crawled links
    if len(links) == 0: # if links to crawl are 0 i.e. all links have been crawled
        break
    elif len(storage) <= len(processed): # if crawled links are somehow more than all links. Possible? ;/
        if len(storage) > 2 + len(seeds): # if you know it, you know it
            break
    print ('%s Level %i: %i URLs' % (run, level + 1, len(links)))
    try:
        flash(extractor, links)
    except KeyboardInterrupt:
        print ('')
        break

if not only_urls:
    for match in bad_scripts:
        if match.startswith(main_url):
            scripts.add(match)
        elif match.startswith('/') and not match.startswith('//'):
            scripts.add(main_url + match)
        elif not match.startswith('http') and not match.startswith('//'):
            scripts.add(main_url + '/' + match)
    # Step 3. Scan the JavaScript files for enpoints
    print ('%s Crawling %i JavaScript files' % (run, len(scripts)))
    flash(jscanner, scripts)

    for url in storage:
        if '=' in url:
            fuzzable.add(url)

    for match in bad_intel:
        for x in match: # because "match" is a tuple
            if x != '': # if the value isn't empty
                intel.add(x)

now = time.time() # records the time at which crawling stopped
diff = (now  - then) # finds total time taken

def timer(diff):
    minutes, seconds = divmod(diff, 60) # Changes seconds into minutes and seconds
    time_per_request = diff / float(len(processed)) # Finds average time taken by requests
    return minutes, seconds, time_per_request
time_taken = timer(diff)
minutes = time_taken[0]
seconds = time_taken[1]
time_per_request = time_taken[2]

# create writer function
def writer(file, lines):
    with open(file, 'w+') as f:
        f.write('\n'.join(lines))

# Step 4. Save the results
if args.dns:
    dnsdumpster(domain_name, output_dir, colors)

if len(storage) > 0:
    writer('%s/links.txt' % output_dir, storage)

if len(files) > 0:
    writer('%s/files.txt' % output_dir, files)

if len(intel) > 0:
    writer('%s/intel.txt' % output_dir, intel)

if len(robots) > 0:
    writer('%s/robots.txt' % output_dir, robots)

if len(failed) > 0:
    writer('%s/failed.txt' % output_dir, failed)

if len(custom) > 0:
    writer('%s/custom.txt' % output_dir, custom)

if len(scripts) > 0:
    writer('%s/scripts.txt' % output_dir, scripts)

if len(fuzzable) > 0:
    writer('%s/fuzzable.txt' % output_dir, fuzzable)

if len(external) > 0:
    writer('%s/external.txt' % output_dir, external)

if len(endpoints) > 0:
    writer('%s/endpoints.txt' % output_dir, endpoints)

# Printing out results
print ('''%s
%s URLs: %i
%s Intel: %i
%s Files: %i
%s Endpoints: %i
%s Fuzzable URLs: %i
%s Custom strings: %i
%s JavaScript Files: %i
%s External References: %i
%s''' % ((('%s-%s' % (red, end)) * 50), good, len(storage), good, 
len(intel), good, len(files), good, len(endpoints), good, len(fuzzable), good,
len(custom), good, len(scripts), good, len(external),
(('%s-%s' % (red, end)) * 50)))

print ('%s Total time taken: %i minutes %i seconds' % (info, minutes, seconds))
print ('%s Average request time: %s seconds' % (info, time_per_request))

if args.export:
    # exporter(directory, format, datasets)
    exporter(output_dir, args.export, {'files': list(files), 'intel': list(intel), 'robots': list(robots), 'custom': list(custom), 'failed': list(failed), 'storage': list(storage), 'scripts': list(scripts), 'external': list(external), 'fuzzable': list(fuzzable), 'endpoints': list(endpoints)})

if not colors: # if colors are disabled
    print ('%s Results saved in %s directory' % (good, output_dir))
else:
    print ('%s Results saved in \033[;1m%s\033[0m directory' % (good, output_dir))
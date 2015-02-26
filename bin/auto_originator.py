#!/usr/bin/python2.7
# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab
'''Simple script to load an interactive originator from cmdline args'''
import sys
from sangoma.switchy.legacy_orig import get_async_originator


req_uri = sys.argv[1]
try:
    load_server = sys.argv[2]
except IndexError:
    load_server = '127.0.0.1'

orig_str = "{{sip_h_X-qa-callback-did=9196}}sofia/qa/{} 9197 xml default"\
    .format(req_uri)

# orig = AsyncOriginator(server=str(load_server), originate_string=orig_str)
orig = get_async_originator(server=str(load_server), originate_string=orig_str)

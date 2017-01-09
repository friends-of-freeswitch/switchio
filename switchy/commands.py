# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Command wrappers and helpers
"""


def build_originate_cmd(dest_url, uuid_str=None, profile='external',
                        gateway=None,  # optional gw name
                        # explicit app + args
                        app_name='park', app_arg_str='',
                        # dp app
                        dp_exten=None, dp_type='xml', dp_context='default',
                        proxy=None,  # first hop uri
                        endpoint='sofia',
                        timeout=60,
                        caller_id='Mr_Switchy',
                        caller_id_num='1112223333',
                        codec='PCMU',
                        abs_codec='',
                        xheaders=None,
                        **kwargs):
    '''Return a formatted `originate` command string conforming
    to the syntax dictated by mod_commands of the form:

    originate <call url> <exten>|&<application_name>(<app_args>) [<dialplan>]
    [<context>] [<cid_name>] [<cid_num>] [<timeout_sec>]

    Parameters
    ----------
    dest_url : str
        call destination url with format <username_uri>@<domain>:<port>
    profile : str
        sofia profile (UA) name to use for making outbound call
    dp_extension: str
        destination dp extension where the originating session (a-leg) will
        processed just after the call is answered
    etc...

    Returns
    -------
    originate command : string or callable
        full cmd string if uuid_str is not None,
        else callable f(uuid_str) -> full cmd string
    '''
    # default params setup
    params = {
        'originate_timeout': timeout,
        'origination_caller_id_name': caller_id,
        'origination_caller_id_number': caller_id_num,
        'originator_codec': codec,
        'absolute_codec_string': abs_codec,
        # must fill this in using a format string placeholder
        'origination_uuid': uuid_str or '{uuid_str}',
        'ignore_display_updates': 'true',
        'ignore_early_media': 'true',
    }

    # set a proxy destination if provided (i.e. the first hop)
    dest_str = ";fs_path=sip:{}".format(proxy) if proxy else ''
    # params['sip_network_destination'] =

    # generate any requested Xheaders
    if xheaders is not None:
        xheader_prefix = 'sip_h_X-'
        for name, val in xheaders.items():
            if xheader_prefix in name:
                params[name] = val
            else:
                params['{}{}'.format(xheader_prefix, name)] = val

    # override with user settings
    params.update(kwargs)

    # render params as strings
    pairs = ['='.join(map(str, pair)) for pair in params.items()]

    # user specified app?
    if dp_exten:  # use dialplan app for outbound channel
        app_part = '{} {} {}'.format(dp_exten, dp_type, dp_context)
    else:  # render app syntax
        app_part = '&{}({})'.format(app_name, app_arg_str)

    # render final cmd str
    profile = profile if gateway is None else 'gateway/{}'.format(gateway)
    call_url = '{}/{}/{}{}'.format(endpoint, profile, dest_url, dest_str)
    if not uuid_str:
        prefix_vars = '{{{{{params}}}}}'.format(params=','.join(pairs))
    else:
        prefix_vars = '{{{params}}}'.format(params=','.join(pairs))

    return 'originate {pv}{call_url} {app_part}'.format(
        pv=prefix_vars, call_url=call_url, app_part=app_part)

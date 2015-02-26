"""
Command wrappers and helpers
"""


def build_originate_cmd(dest_url, uuid_str=None, profile='external',
                        dp_exten='park', dp_type='xml', dp_context='default',
                        proxy=None,
                        app_name=None, app_arg_str='',
                        timeout=60,
                        caller_id='Mr_Switchy',
                        codec='PCMU',
                        abs_codec='',
                        xheaders={},
                        extra_params={},
                        **kwargs):
    '''
    Return a formatted 'originate' command string conforming
    to the syntax dictated by mod_commands of the form:

    originate <call url> <exten>|&<application_name>(<app_args>) [<dialplan>]
    [<context>] [<cid_name>] [<cid_num>] [<timeout_sec>]

    Parameters
    ----------
    dest_url : str
        call destination url with format <username_uri>@<domain>:<port>
    profile : str
        sofia profile (ua) name to use for making outbound call
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
        'originate_caller_id_name': caller_id,
        'originator_codec': codec,
        'absolute_codec_string': abs_codec,
        # must fill this in using a format string placeholder
        'origination_uuid': uuid_str or '{uuid_str}',
    }

    # set a proxy destination if provided (i.e. the first hop)
    dest_str = ";fs_path=sip:{}".format(proxy) if proxy else ''
        # params['sip_network_destination'] =

    # generate any requested Xheaders
    xheader_prefix = 'sip_h_X-'
    for name, val in xheaders.iteritems():
        if xheader_prefix in name:
            params[name] = val
        else:
            params['{}{}'.format(xheader_prefix, name)] = val

    # override with user settings
    params.update(extra_params)

    # render params as strings
    pairs = ['='.join(map(str, pair)) for pair in params.iteritems()]

    # user specified app?
    if app_name is None:  # use dialplan app
        app_part = '{} {} {}'.format(dp_exten, dp_type, dp_context)
    else:  # render app syntax
        app_part = '&{}({})'.format(app_name, app_arg_str)

    # render final cmd str
    call_url = 'sofia/{}/{}{}'.format(profile, dest_url, dest_str)
    if not uuid_str:
        prefix_vars = '{{{{{params}}}}}'.format(params=','.join(pairs))
    else:
        prefix_vars = '{{{params}}}'.format(params=','.join(pairs))

    return 'originate {pv}{call_url} {app_part}'.format(
        pv=prefix_vars, call_url=call_url, app_part=app_part)

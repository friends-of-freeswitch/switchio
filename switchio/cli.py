# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import re
import os
import sys
import importlib
import time
import click
import switchio


@click.group()
def cli():
    pass


@cli.command('list-apps')
@click.argument('module', nargs=1, required=False)
def list_apps(module):
    builtin_mods = switchio.apps.load()
    click.echo(
        'Collected {} built-in apps from {} modules:\n'
        .format(len(list(switchio.apps.iterapps())), len(builtin_mods))
    )
    for mod, apps in switchio.apps.groupbymod():
        click.echo('{}:\n'.format(mod))
        for name, app in apps:
            click.echo(
                ' - {}: {}'.format(
                 name, app.__doc__ or '(No help for app {})\n'.format(name)),
            )


# XXX plot command is only available when matplotlib is installed
@cli.command()
@click.argument('file-name', nargs=1, required=True,
                type=click.Path(exists=True))
def plot(file_name):
    import matplotlib  # errors if not installed
    from switchio.apps import measure
    df = measure.load(file_name)
    click.echo('Plotting {} ...\n'.format(file_name))
    df._plot(block=True)


def get_apps(appnames):
    """Retrieve and return a list of app types from a sequence of names.
    """
    apps = []
    switchio.apps.load()
    for appspec in appnames:
        args = {}
        path, _, attr = appspec.partition(':')
        appname, _, argspec = attr.partition('/')
        if argspec:
            args = dict(v.split('=') for v in argspec.split(','))

        # module syntax (`mod.submod.AppName` or `mod.submod:AppName`)
        if not os.path.isfile(path) and '.' in appname:
            if not attr:
                path, attr = os.path.splitext(path)
                attr = attr.lstrip('.')
            mod = importlib.import_module(path)

        # file path syntax (`/path/to/my.py:AppName`)
        elif os.path.isfile(path):
            basename = os.path.basename(path)
            modpath, ext = os.path.splitext(basename)
            assert ext == '.py', "{} is not a Python module?".format(
                appname)
            sys.path.append(os.path.dirname(os.path.expanduser(path)))
            mod = __import__(modpath)
        else:  # load a built-in app by name
            cls = switchio.apps.get(appname)
            attr = getattr(cls, '__name__', None)
            mod = None

        if not attr:
            raise click.ClickException(
                "`{}` does not specify an app name. Use `{}:AppName`"
                .format(appname, appname))
        if mod:
            cls = getattr(mod, attr)
        if not cls:
            raise click.ClickException(
                "Unknown app '{}'\nUse list-apps command "
                "to list available apps".format(appname)
            )
        apps.append((cls, args))

    return apps


@cli.command()
@click.argument('hosts', nargs=-1, required=True)
@click.option('--proxy',
              default=None,
              help='Hostname or IP address of the proxy '
              'device (this is usually the device you are testing)')
@click.option('--dest-url',
              default=None,
              help='Request-URI string')
@click.option('--profile',
              default='internal',
              help='Profile to use for originating calls')
@click.option('--gateway',
              default=None,
              help='Gateway to use for originating calls')
@click.option('--rate',
              default=None, help='Call rate')
@click.option('--limit',
              default=None, help='Maximum number of concurrent calls')
@click.option('--max-offered',
              default=None,
              help='Maximum number of calls to place '
              'before stopping the program')
@click.option('--duration', default=None, help='Duration of calls in seconds')
@click.option('--interactive/--non-interactive',
              default=False,
              help='Whether to jump into an interactive session '
              'after setting up the call originator')
@click.option('--app', default=['Bert'], multiple=True,
              help='switchio application to load. You can pass this option '
              'multiple times and the apps are loaded in the order specified. '
              'See the \'list-apps\' command to list available apps. For every '
              'listed app you can optionally specify arguments by adding a slash '
              'followed by comma-separated k=v pairs for every argument. (e.g '
              'Bert/bert_timer_name=soft,bert_timeout_ms=5000)')
@click.option('--password', default='ClueCon',
              help='Password to use for ESL authentication')
@click.option('--metrics-file',
              default=None, help='Store metrics at the given file location')
@click.option('-l', '--loglevel', default='INFO',
              help='Set the Python logging level')
def dial(hosts, proxy, dest_url, profile, gateway, rate, limit, max_offered,
         duration, interactive, app, metrics_file, loglevel, password):
    """Spin up an auto-dialer.
    """
    log = switchio.utils.log_to_stderr(loglevel)
    log.propagate = False

    dialer = switchio.get_originator(
        hosts,
        rate=int(rate) if rate else None,
        limit=int(limit) if limit else None,
        max_offered=int(max_offered) if max_offered else None,
        duration=int(duration) if duration else None,
        auto_duration=True if not duration else False,
        password=password,
    )
    apps = get_apps(app)
    for cls, args in apps:
        dialer.load_app(cls, ppkwargs=args)

    # Prepare the originate string for each slave
    # depending on the profile name and network settings
    # configured for that profile in that particular slave
    p = re.compile('.+?BIND-URL\s+?.+?@(.+?):(\d+).+?\s+',
                   re.IGNORECASE | re.DOTALL)
    for client in dialer.pool.clients:
        status = client.client.api(
            'sofia status profile {}'.format(profile)).getBody()
        m = p.match(status)
        if not m:
            raise click.ClickException('Slave {} does not have a profile '
                                       'named \'{}\' running'
                                       .format(client.host, profile))
        # configure originate cmd(s)
        ip = m.group(1)
        port = m.group(2)
        if dest_url is None:
            dest_url = 'switchio@{}:{}'.format(ip, port)
        # The originate cmd must route the call back to us using the specified
        # proxy (the device under test)
        if proxy is None:
            proxy = dest_url
        log.info('Slave {} SIP address is at {}:{}'.format(
            client.host, ip, port))
        client.set_orig_cmd(dest_url=dest_url, profile=profile,
                            gateway=gateway, app_name='park',
                            proxy='{}'.format(proxy))

    log.info('Starting load test for server {} at {}cps using {} hosts'
             .format(proxy, dialer.rate, len(hosts)))
    click.echo(dialer)
    if interactive:
        try:
            import IPython
            IPython.start_ipython(argv=[], user_ns=locals())
        except ImportError:
            try:
                # optional, will allow Up/Down/History in the console
                import readline
            except ImportError:
                pass

            # load built-in console
            import code
            vars = globals().copy()
            vars.update(locals())
            shell = code.InteractiveConsole(vars)
            shell.interact()

        dialer.shutdown()
        click.echo(dialer)
    else:
        dialer.start()
        while dialer.state != 'STOPPED':
            try:
                time.sleep(1)
                click.echo(dialer)
            except KeyboardInterrupt:
                dialer.shutdown()
                click.echo(dialer)

    try:
        while True:
            active_calls = dialer.count_calls()
            if active_calls <= 0:
                break
            click.echo(
                'Waiting on {} active calls to finish'
                .format(active_calls)
            )
            time.sleep(1)
    except KeyboardInterrupt:
        dialer.shutdown()

    if metrics_file:
        click.echo('Storing test metrics at {}'.format(metrics_file))
        dialer.measurers.to_store(metrics_file)

    click.echo('Dialing session completed!')


@cli.command('serve')
@click.argument('hosts', nargs=-1, required=True)
@click.option('--app', default=[], multiple=True,
              help='switchio to load (can pass multiple times '
              'with apps loaded in the order specified).'
              '(see list-apps command to list available apps)')
@click.option('--password', default='ClueCon',
              help='Password to use for ESL authentication')
@click.option('-l', '--loglevel', default='INFO',
              help='Set the Python logging level')
@click.option('--app-header', default='default',
              help='Event header to use for activating provided apps')
@click.option('--profile',
              default='internal',
              help='Profile to use for originating calls')
def serve(hosts, profile, app, loglevel, password, app_header):
    """Start a switchio service and block forever.
    """
    log = switchio.utils.log_to_stderr(loglevel.upper())
    service = switchio.Service(hosts, password=password)
    apps = get_apps(app)
    if apps:
        for cls, kwargs in apps:
            service.apps.load_app(cls, app_id=app_header, ppkwargs=kwargs)

    service.run()

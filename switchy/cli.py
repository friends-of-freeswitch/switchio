# vim: tabstop=4 softtabstop=4 shiftwidth=4 textwidth=80 smarttab expandtab
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import re
import time
import click
import switchy


@click.group()
def cli():
    pass


@cli.command('list-apps')
@click.argument('module', nargs=1, required=False)
def list_apps(module):
    builtin_mods = switchy.apps.load()
    click.echo(
        'Collected {} built-in apps from {} modules:\n'
        .format(len(list(switchy.apps.iterapps())), len(builtin_mods))
    )
    for mod, apps in switchy.apps.groupbymod():
        click.echo('{}:\n'.format(mod))
        for name, app in apps:
            click.echo('`{}`: {}'.format(
                name, app.__doc__ or '(No help for app {})'.format(name))
            )


# XXX plot command is only available when matplotlib is installed
@cli.command()
@click.argument('file-name', nargs=1, required=True,
                type=click.Path(exists=True))
def plot(file_name):
    import matplotlib
    from switchy.apps.measure import metrics
    m = metrics.load(file_name)
    click.echo('Plotting {} ...\n'.format(file_name))
    m.plot()


@cli.command()
@click.argument('slaves', nargs=-1, required=True)
@click.option('--proxy',
              default=None,
              help='Hostname or IP address of the proxy '
              'device (this is usually the device you are testing)',
              required=True)
@click.option('--profile',
              default='internal',
              help='Profile to use for outbound calls in the load slaves')
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
@click.option('--debug/--no-debug',
              default=False, help='Whether to enable debugging')
@click.option('--app', default='Bert',
              help='Switchy application to execute '
              '(see list-apps command to list available apps)')
@click.option('--metrics-file',
              default=None, help='Store metrics at the given file location')
def run(slaves, proxy, profile, rate, limit, max_offered,
        duration, interactive, debug, app, metrics_file):
    log = switchy.utils.log_to_stderr("INFO")

    # Check if the specified (or default) app is valid
    switchy.apps.load()
    cls = switchy.apps.get(app)
    if not cls:
        raise click.ClickException('Unknown app {}. Use list-apps command '
                                   'to list available apps'.format(app))

    # TODO: get_originator() receives an apps tuple (defaults to Bert) to
    # select the application we should accept --app multi argument list to
    # set multiple apps
    o = switchy.get_originator(
        slaves,
        apps=(cls,),
        rate=int(rate) if rate else None,
        limit=int(limit) if limit else None,
        max_offered=int(max_offered) if max_offered else None,
        duration=int(duration) if duration else None,
        auto_duration=True if not duration else False,
    )

    # Prepare the originate string for each slave
    # depending on the profile name and network settings
    # configured for that profile in that particular slave
    p = re.compile('.+?BIND-URL\s+?.+?@(.+?):(\d+).+?\s+',
                   re.IGNORECASE | re.DOTALL)
    for c in o.pool.clients:
        status = c.client.api('sofia status profile {}'
                              .format(profile)).getBody()
        m = p.match(status)
        if not m:
            raise click.ClickException('Slave {} does not have a profile '
                                       'named \'{}\' running'
                                       .format(c.host, profile))
        ip = m.group(1)
        port = m.group(2)
        # The originate cmd must route the call back to us using the specified
        # proxy (the device under test)
        log.info('Slave {} SIP address is at {}:{}'.format(c.host, ip, port))
        c.set_orig_cmd(dest_url='switchy@{}:{}'.format(ip, port),
                       profile=profile, app_name='park',
                       proxy='{}'.format(proxy))

    log.info('Starting load test for server {} at {}cps using {} slaves'
               .format(proxy, o.rate, len(slaves)))
    click.echo(o)
    if interactive:
        try:
            import IPython
            IPython.embed()
        except ImportError:
            try:
                # optional, will allow Up/Down/History in the console
                import readline
            except ImportError:
                pass
            import code
            vars = globals().copy()
            vars.update(locals())
            shell = code.InteractiveConsole(vars)
            shell.interact()

        o.shutdown()
        click.echo(o)
    else:
        o.start()
        while o.state != 'STOPPED':
            try:
                time.sleep(1)
                click.echo(o)
            except KeyboardInterrupt:
                o.shutdown()
                click.echo(o)

    while True:
        active_calls = o.count_calls()
        if active_calls <= 0:
            break
        click.echo('Waiting on {} active calls to finish'.format(active_calls))
        time.sleep(1)

    if metrics_file:
        click.echo('Storing test metrics at {}'.format(metrics_file))
        o.metrics.dump(metrics_file)

    click.echo('Load test finished!')

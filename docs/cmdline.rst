Switchy Command Line
====================
Switchy provides a convenient cli to initiate load tests with the help
of click_. The program is installed as `switchy`::

    $ switchy
    Usage: switchy [OPTIONS] COMMAND [ARGS]...

    Options:
      --help  Show this message and exit.

    Commands:
      list-apps
      plot
      run

A few sub-commands are provided.
For example you can list the applications available (*apps* determine call flows)::

    $ switchy list-apps
    Collected 5 built-in apps from 7 modules:

    switchy.apps.bert:

    `Bert`: Call application which runs the bert test application on both legs of a call

        See the docs for `mod_bert`_ and discussion by the author `here`_.

        .. _mod_bert:
            https://freeswitch.org/confluence/display/FREESWITCH/mod_bert
        .. _here:
            https://github.com/moises-silva/freeswitch/issues/1

    switchy.apps.players:

    `TonePlay`: Play a 'milli-watt' tone on the outbound leg and echo it back on the inbound

    `PlayRec`: Play a recording to the callee and record it onto the local file system

        This app can be used in tandem with MOS scoring to verify audio quality.
        The filename provided must exist in the FreeSWITCH sounds directory such that
        ${FS_CONFIG_ROOT}/${sound_prefix}/<category>/<filename> points to a valid wave file.

    switchy.apps.dtmf:

    `DtmfChecker`: Play dtmf tones as defined by the iterable attr `sequence` with tone `duration`.
        Verify the rx sequence matches what was transmitted.  For each session which is answered start
        a sequence check. For any session that fails digit matching store it locally in the `failed` attribute.

    switchy.apps.routers:

    `Bridger`: Bridge sessions within a call an arbitrary number of times.  


The applications listed can be used with the `--app` option to the `run` sub-command.
`run` is the main sub-command used to start a load test. Here is the help::

    $ switchy run --help
    Usage: switchy run [OPTIONS] SLAVES...

    Options:
      --proxy TEXT                    Hostname or IP address of the proxy device
                                      (this is usually the device you are testing)
                                      [required]
      --profile TEXT                  Profile to use for outbound calls in the
                                      load slaves
      --rate TEXT                     Call rate
      --limit TEXT                    Maximum number of concurrent calls
      --max-offered TEXT              Maximum number of calls to place before
                                      stopping the program
      --duration TEXT                 Duration of calls in seconds
      --interactive / --non-interactive
                                      Whether to jump into an interactive session
                                      after setting up the call originator
      --debug / --no-debug            Whether to enable debugging
      --app TEXT                      Switchy application to execute (see list-
                                      apps command to list available apps)
      --metrics-file TEXT             Store metrics at the given file location
      --help                          Show this message and exit.


The `SLAVES` argument can be one or more IP's or hostnames for each configured FreeSWITCH :term:`slave`
used to originate traffic. The `--proxy` option is required and must be the IP address or hostname
of the device you are testing. All slaves will direct traffic to the specified proxy.

The other options are not strictly required but typically you will want to at least specify a given call rate
using the `--rate` option, max number of concurrent calls (erlangs) with `--limit` and possibly max number of
calls offered with `--max-offered`.

For example, to start a test using an slave located at `1.1.1.1` to test device at `2.2.2.2` with a maximum of
`2000` calls at `30` calls per second and stopping after placing `100,000` calls you can do::

    $ switchy run 1.1.1.1 --profile external --proxy 2.2.2.2 --rate 30 --limit 2000 --max-offered 100000

    Slave 1.1.1.1 SIP address is at 1.1.1.1:5080
    Starting load test for server 2.2.2.2 at 30cps using 1 slaves
    ...

Note that the `--profile` option is also important and the profile must exist already for all specified slaves.

In this case the call duration would be automatically calculated to sustain that call rate and that max calls
exactly, but you can tweak the call duration in seconds using the `--duration` option.

Additionally you can use the `--metrics-file` option to store call metrics in a file.
You can then use the `plot` sub-command to generate graphs of the collected data using
`matplotlib` if installed.

.. _click: http://click.pocoo.org/5/

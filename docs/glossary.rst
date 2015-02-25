Glossary
--------
.. glossary::
    caller
        SIP user agent which originates or 'initiates' a session and is
        the start point for a *call*

    callee
        SIP user agent which receives a session and is the end point for
        a *call*

    originator
        The FreeSWITCH slave server(s) which will originate calls thus
        acting as the caller(s) in a testing environment

    intermediary
        The user agent(s) which will be the **first hop** which SIP requests
        will be sent **to** by the originating *FreeSWITCH* slave's user
        agent. This UA node is normally expected to be the server/sofware
        under test.
    slave
        Colloquial name given to *FreeSWITCH* processes which are
        controlled by Switchy. Throughout this documentation *slave
        server* and *process* are often used interchangably since, for
        most deployments, a single *FreeSWITCH* process is run on
        each physical server.

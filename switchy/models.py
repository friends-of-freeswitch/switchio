# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Models representing freeSWITCH entities
"""
import time
import utils
from collections import deque
from multiproc import mp


class JobError(utils.ESLError):
    pass


class Events(object):
    """Event collection which for most intents and purposes should quack like
    a collections.deque. Data lookups are delegated to the internal
    deque of events in lilo order.
    """
    def __init__(self, event=None):
        self._events = deque()
        if event is not None:
            # add initial event to our queue
            self.update(event)

    def __repr__(self):
        return repr(self._events)

    def update(self, event):
        '''Append an ESL.ESLEvent
        '''
        self._events.appendleft(event)

    def __len__(self):
        return len(self._events)

    def __iter__(self):
        for ev in self._events:
            yield ev

    def get(self, key, default=None):
        """Return default if not found
        Should be faster then handling the key error?
        """
        # XXX would a map() be faster here?
        # iterate from most recent event
        for ev in self._events:
            value = ev.getHeader(str(key))
            if value:
                return value
        return default

    def __getitem__(self, key):
        '''Return either the value corresponding to variable 'key'
        or if type(key) == (int or slice) then return the corresponding
        event from the internal deque
        '''
        value = self.get(key)
        if value:
            return value
        else:
            if isinstance(key, (int, slice)):
                return self._events[key]
            raise KeyError(key)

    def pprint(self, index=0):
        """Print serialized event data in chronological order to stdout
        """
        for ev in reversed(self._events):
            print(ev.serialize())


class Session(object):
    '''Type to represent FS Session state
    '''
    create_ev = 'CHANNEL_CREATE'

    # TODO: eventually uuid should be removed
    def __init__(self, event, uuid=None, con=None):
        self.events = Events(event)
        self.uuid = uuid or self.events['Unique-ID']
        self.con = con
        # sub-namespace for apps to set/get state
        self.vars = {}

        # external attributes
        self.duration = 0
        self.bg_job = None
        self.answered = False
        self.call = None
        self.hungup = False

        # time stamps
        self.times = {}.fromkeys(
            ('create', 'answer', 'req_originate', 'originate', 'hangup'))
        self.times['create'] = utils.get_event_time(event)

    def __str__(self):
        return str(self.uuid)

    def __dir__(self):
        # TODO: use a transform func to provide __getattr__
        # access to event data
        return utils.dirinfo(self)

    def __getattr__(self, name):
        if 'variable' in name:
            try:  # to acquire from channel variables
                return self.events[name]
            except KeyError:
                pass
        return object.__getattribute__(self, name)

    def __getitem__(self, key):
        try:
            return self.events[key]
        except KeyError:
            raise KeyError("'{}' not found for session '{}'"
                           .format(key, self.uuid))

    def get(self, key, default=None):
        '''Get data pertaining to session state as updated via events

        Parameters
        ----------
        name : string
            name of the variable to return the value for
        '''
        return self.events.get(key, default)

    def update(self, event):
        '''Update state/data using an ESL.ESLEvent
        '''
        self.events.update(event)

    def __enter__(self, connection):
        self.con = connection
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.con = None

    @property
    def appname(self):
        return self.get('variable_switchy_app')

    @property
    def time(self):
        """Time stamp for the most recent received event
        """
        return utils.get_event_time(self.events[0])

    @property
    def uptime(self):
        """Time elapsed since the `create_ev` to the most recent received event
        """
        return self.time - self.times['create']

    # call control / 'mod_commands' methods
    # TODO: dynamically add @decorated functions to this class
    # and wrap them using functools.update_wrapper ...?

    def setvar(self, var, value):
        """Set variable to value
        """
        self.broadcast("set::{}={}".format(var, value))

    def setvars(self, params):
        """Set all variables in map `params` with a single command
        """
        pairs = ('='.join(map(str, pair)) for pair in params.iteritems())
        self.con.api("uuid_setvar_multi {} {}".format(
            self.uuid, ';'.join(pairs)))

    def unsetvar(self, var):
        """Unset a channel var
        """
        self.broadcast("unset::{}".format(var))

    def answer(self):
        self.broadcast("answer::")

    def hangup(self, cause='NORMAL_CLEARING'):
        '''Hangup this session with the given cause

        Parameters
        ----------
        cause : string
            hangup type keyword
        '''
        self.con.api(str('uuid_kill %s %s' % (self.uuid, cause)))

    def sched_hangup(self, timeout, cause='NORMAL_CLEARING'):
        '''Schedule this session to hangup after timeout seconds

        Parameters
        ----------
        timeout : float
            timeout in seconds
        cause : string
            hangup cause code
        '''
        self.con.api('sched_hangup +{} {} {}'.format(timeout,
                     self.uuid, cause))

    def clear_tasks(self):
        '''Clear all scheduled tasks for this session
        '''
        self.con.api('sched_del {}'.format(self.uuid))

    def sched_dtmf(self, delay, sequence, tone_duration=None):
        '''Schedule dtmf sequence to be played on this channel

        Parameters
        ----------
        delay : float
            scheduled future time when dtmf tones should play
        sequence : string
            sequence of dtmf digits to play
        '''
        cmd = 'sched_api +{} none uuid_send_dtmf {} {}'.format(
            delay, self.uuid, sequence)
        if tone_duration is not None:
            cmd += ' @{}'.format(tone_duration)
        self.con.api(cmd)

    def send_dtmf(self, sequence, duration='w'):
        '''Send a dtmf sequence with constant tone durations
        '''
        self.con.api('uuid_send_dtmf {} {} @{}'.format(
                     self.uuid, sequence, duration))

    def playback(self, args, start_sample=None, endless=False,
                 leg='aleg', params=None):
        '''Playback a file on this session

        Parameters
        ----------
        args : string or tuple
            arguments or path to audio file for playback app
        leg : string
            call leg to transmit the audio on
        '''
        app = 'endless_playback' if endless else 'playback'
        pairs = ('='.join(map(str, pair))
                 for pair in params.iteritems()) if params else ''

        delim = ';'
        if isinstance(args, str):
            args = (args,)
        else:  # set a stream file delimiter
            self.setvar('playback_delimiter', delim)

        self.broadcast(
            '{app}::{varset}{streams}{start} {leg}'.format(
                app=app,
                streams=delim.join(args),
                start='@@{}'.format(start_sample) if start_sample else '',
                leg=leg,
                varset='{{{vars}}}'.format(','.join(pairs)) if pairs else '',
            )
        )

    def start_record(self, path, rx_only=False, stereo=False, rate=16000):
        '''Record audio from this session to a local file on the slave filesystem
        using the `record_session`_ cmd. By default recordings are sampled at
        16kHz.

        .. _record_session:
            https://freeswitch.org/confluence/display/FREESWITCH/record_session
        '''
        if rx_only:
            self.setvar('RECORD_READ_ONLY', 'true')
        elif stereo:
            self.setvar('RECORD_STEREO', 'true')

        self.setvar('record_sample_rate', '{}'.format(rate))
        self.broadcast('record_session::{}'.format(path))

    def stop_record(self, path='all', delay=0):
        '''Stop recording audio from this session to a local file on the slave
        filesystem using the `stop_record_session`_ cmd

        .. _stop_record_session:
            https://freeswitch.org/confluence/display/FREESWITCH/mod_dptools%3A+stop_record_session
        '''
        if delay:
            self.con.api(
                "sched_api +{delay} none uuid_broadcast {sessid} "
                "stop_record_session::{path}".
                format(sessid=self.uuid, delay=delay, path=path)
            )
        else:
            self.broadcast('stop_record_session::{}'.format(path))

    def record(self, action, path, rx_only=True):
        '''Record audio from this session to a local file on the slave filesystem
        using the `uuid_record`_ command:
            uuid_record <uuid> [start|stop|mask|unmask] <path> [<limit>]

        .. _uuid_record:
            https://freeswitch.org/confluence/display/FREESWITCH/mod_commands#mod_commands-uuid_record
        '''
        self.con.api('uuid_record {} {} {}'.format(self.uuid, action, path))

    def echo(self):
        '''Echo back all audio recieved
        '''
        self.broadcast('echo::')

    def bypass_media(self, state):
        '''Re-invite a bridged node out of the media path for this session
        '''
        if state:
            self.con.api('uuid_media off {}'.format(self.uuid))
        else:
            self.con.api('uuid_media {}'.format(self.uuid))

    def start_amd(self, delay=None):
        self.con.api('avmd {} start'.format(self.uuid))
        if delay is not None:
            self.con.api('sched_api +{} none avmd {} stop'.format(
                         int(delay), self.uuid))

    def stop_amd(self):
        self.con.api('avmd {} stop'.format(self.uuid))

    def park(self):
        '''Park this session
        '''
        self.con.api('uuid_park {}'.format(self.uuid))

    def broadcast(self, path, leg=''):
        """Usage:
        uuid_broadcast <uuid> <path> [aleg|bleg|both]

        Execute an application on a chosen leg(s) with optional hangup
        afterwards:
        Usage:
            uuid_broadcast <uuid> app[![hangup_cause]]::args [aleg|bleg|both]
        """
        # FIXME: this should use the EventListener SOCKET_DATA handler!!
        #       so that we are actually alerted of cmd errors!
        self.con.api('uuid_broadcast {} {} {}'.format(self.uuid, path, leg))

    def bridge(self, dest_url="${sip_req_uri}",
               profile="${sofia_profile_name}",
               proxy=None,
               params=None):
        """Bridge this session using `uuid_broadcast`.
        By default the current profile is used to bridge to the requested user.
        """
        pairs = ('='.join(map(str, pair))
                 for pair in params.iteritems()) if params else ''

        self.broadcast(
            "bridge::{{{varset}}}sofia/{}/{}{dest}".format(
                profile, dest_url, varset=','.join(pairs),
                dest=';fs_path=sip:{}'.format(proxy) if proxy else ''
            )
        )

    def breakmedia(self):
        '''Stop playback of media on this session and move on in the dialplan
        '''
        self.con.api('uuid_break {}'.format(self.uuid))

    def mute(self, direction='write', level=1):
        """Mute the current session. `level` determines the degree of comfort
        noise to generate if > 1.
        """
        self.con.api(
            'uuid_audio {uuid} {cmd} {direction} mute {level}'
            .format(
                uuid=self.uuid,
                cmd='start',
                direction=direction,
                level=1 if level else 0,
            )
        )

    def unmute(self, **kwargs):
        """Unmute the write buffer for this session
        """
        self.mute(level=0, **kwargs)

    def is_inbound(self):
        """Return bool indicating whether this is an inbound session
        """
        return self['Call-Direction'] == 'inbound'

    def is_outbound(self):
        """Return bool indicating whether this is an outbound session
        """
        return self['Call-Direction'] == 'outbound'


class Call(object):
    '''A collection of sessions which a compose a call
    '''
    def __init__(self, uuid, session):
        self.uuid = uuid
        self.sessions = deque()
        self.sessions.append(session)
        self._firstref = session
        self._lastref = None
        # sub-namespace for apps to set/get state
        self.vars = {}

    def __repr__(self):
        return "<{}({}, {} sessions)>".format(
            type(self).__name__, self.uuid, len(self.sessions))

    def append(self, sess):
        """Append a session to this call and update the ref to the last
        recently added session
        """
        self.sessions.append(sess)
        self._lastref = sess

    def hangup(self):
        """Hangup up this call
        """
        if self.first:
            self.first.hangup()

    @property
    def last(self):
        '''A reference to the session making up the final leg of this call
        '''
        return self._lastref

    @property
    def first(self):
        '''A reference to the session making up the initial leg of this call
        '''
        return self._firstref

    def get_peer(self, sess):
        """Convenience helper which can determine whether `sess` is one of
        `first` or `last` and returns the other when the former is true
        """
        if sess:
            if sess is self.first:
                return self.last
            elif sess is self.last:
                return self.first

        return None


class Job(object):
    '''Type to hold data and deferred execution for a background job.
    The interface closely matches `multiprocessing.pool.AsyncResult`.

    Parameters
    ----------
    uuid : string
        job uuid returned directly by SOCKET_DATA event
    sess_uuid : string
        optional session uuid if job is associated with an active
        FS session
    '''
    class TimeoutError(Exception):
        pass

    def __init__(self, event, sess_uuid=None, callback=None, client_id=None,
                 kwargs={}):
        self.events = Events(event)
        self.uuid = self.events['Job-UUID']  # event.getHeader('Job-UUID')
        self.sess_uuid = sess_uuid
        self.launch_time = time.time()
        self.cid = client_id  # placeholder for client ident

        # when the job returns use this callback
        self._cb = callback
        self.kwargs = kwargs
        self._result = None
        self._failed = False
        self._ev = None  # signal/sync job completion

    @property
    def result(self):
        '''The final result
        '''
        return self.get()

    @property
    def _sig(self):
        if not self._ev:
            self._ev = mp.Event()  # signal/sync job completion
            if self._result:
                self._ev.set()
        return self._ev

    def __call__(self, resp, *args, **kwargs):
        if self._cb:
            self.kwargs.update(kwargs)
            self._result = self._cb(resp, *args, **self.kwargs)
        else:
            self._result = resp
        if self._ev:  # don't allocate an event if unused
            self._ev.set()  # signal job completion
        return self._result

    def fail(self, resp, *args, **kwargs):
        '''Fail this job optionally adding an exception for its result
        '''
        self._failed = True
        self._result = JobError(self(resp, *args, **kwargs))

    def get(self, timeout=None):
        '''Get the result for this job waiting up to `timeout` seconds.
        Raises `TimeoutError` on if job does complete within alotted time.
        '''
        ready = self._sig.wait(timeout)
        if ready:
            return self._result
        elif timeout:
            raise TimeoutError("Job not complete after '{}' seconds"
                               .format(timeout))

    def ready(self):
        '''Return bool indicating whether job has completed
        '''
        return self._sig.is_set()

    def wait(self, timeout=None):
        '''Wait until job has completed or `timeout` has expired
        '''
        self._sig.wait(timeout)

    def successful(self):
        '''Return bool determining whether job completed without error
        '''
        assert self.ready(), 'Job has not completed yet'
        return not self._failed

    def update(self, event):
        '''Update job state/data using an event
        '''
        self.events.update(event)

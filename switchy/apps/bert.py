# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Bert testing
"""
from collections import deque
from ..apps import app
from ..marks import event_callback
from ..utils import get_logger, CommandError


@app
class Bert(object):
    """Call application which runs the bert test application on both
    legs of a call

    See the docs for `mod_bert`_ and discussion by the author `here`_.

    .. _mod_bert:
        https://freeswitch.org/confluence/display/FREESWITCH/mod_bert
    .. _here:
        https://github.com/moises-silva/freeswitch/issues/1
    """
    bert_sync_lost_var = 'bert_stats_sync_lost'

    def prepost(self, client, listener, **opts):
        self.log = get_logger(self.__class__.__name__)
        self._two_sided = False  # toggle whether to run bert on both ends
        self.opts = {
            'bert_timer_name': 'soft',
            'bert_max_err': '30',
            'bert_timeout_ms': '3000',
            'bert_hangup_on_error': 'yes',
            "jitterbuffer_msec": "100:200:40",
            'absolute_codec_string': 'PCMU',
            # "bert_debug_io_file": "/tmp/bert_debug_${uuid}",
        }
        self.opts.update(opts)
        self.log.debug("using mod_bert config: {}".format(self.opts))

        # make sure the module is loaded
        try:
            client.api('reload mod_bert')
        except CommandError:
            self.log.debug("mod_bert already loaded")

        # collections of failed sessions
        self.lost_sync = deque(maxlen=1e3)
        self.timed_out = deque(maxlen=1e3)
        yield

    @property
    def hangup_on_error(self):
        """Toggle whether to hangup calls when a bert test fails
        """
        return {
            'yes': True,
            'no': False
        }[self.opts.get('bert_hangup_on_error', 'no')]

    @hangup_on_error.setter
    def hangup_on_error(self, val):
        self.opts['bert_hangup_on_error'] = {
            True: 'yes',
            False: 'no'
        }[val]

    @property
    def two_sided(self):
        '''Toggle whether to run the `bert_test` application
        on all sessions of the call. Leaving this `False` means
        all other legs will simply run the `echo` application.
        '''
        return self._two_sided

    @two_sided.setter
    def two_sided(self, enable):
        assert isinstance(enable, bool)
        self._two_sided = enable

    @event_callback('CHANNEL_PARK')
    def on_park(self, sess):
        '''Knows how to get us riled up
        '''
        # assumption is that inbound calls will be parked immediately
        if sess.is_inbound():
            sess.answer()  # next step will be in answer handler
            sess.setvars(self.opts)
            if self._two_sided:  # bert run on both sides
                sess.broadcast('bert_test::')
            else:  # one-sided looping audio back to source
                sess.broadcast('echo::')

        # for outbound calls the park event comes AFTER the answer
        # initiated by the inbound leg given that the originate command
        # specified the `park` application as its argument
        if sess.is_outbound():
            sess.setvars(self.opts)
            sess.broadcast('bert_test::')

    desync_stats = (
        "sync_lost_percent",
        "sync_lost_count",
        "cng_count",
        "err_samples"
    )

    # custom event handling
    @event_callback('mod_bert::lost_sync')
    def on_lost_sync(self, sess):
        """Increment counters on synchronization failure

        The following stats can be retrieved using the latest version of
        mod_bert:

            sync_lost_percent - Error percentage within the analysis window
            sync_lost_count - How many times sync has been lost
            cng_count - Counter of comfort noise packets
            err_samples - Number of samples that did not match the sequence
        """
        partner = sess.call.sessions[-1]  # partner is the final callee UA
        self.log.error(
            'BERT Lost Sync on session {} with stats:\n{}'.format(
                sess.uuid, "\n".join(
                    "{}: {}".format(name, sess.get(name, 'n/a'))
                    for name in self.desync_stats)
            )
        )
        # only set vars on the first de-sync
        if not hasattr(sess, 'bert_lost_sync_cnt'):
            sess.vars['bert_lost_sync_cnt'] = 0
            # mod_bert does not know about the peer session
            sess.setvar(self.bert_sync_lost_var, 'true')
            partner.setvar(self.bert_sync_lost_var, 'true')
            self.lost_sync.append(sess)
        # count de-syncs
        sess.vars['bert_lost_sync_cnt'] += 1
        sess.vars['bert_sync'] = False

    @event_callback('mod_bert::timeout')
    def on_timeout(self, sess):
        """Mark session as bert time out
        """
        sess.vars['bert_timeout'] = True
        self.log.error('BERT timeout on session {}'.format(sess.uuid))
        self.timed_out.append(sess)

    @event_callback('mod_bert::in_sync')
    def on_synced(self, sess):
        sess.vars['bert_sync'] = True
        self.log.debug('BERT sync on session {}'.format(sess.uuid))

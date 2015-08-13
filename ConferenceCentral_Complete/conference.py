#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime, time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import TypeOfSession

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

CONFERENCE_DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
    "sessionIds": [],
    "featuredSpeaker": "",
}

SESSION_DEFAULTS = {
    "highlights": [ "Free", "Beer"],
    "duration": 0,
    "typeOfSession": TypeOfSession.NOT_SPECIFIED,
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }


CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)


CONF_TYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    sessionType=messages.StringField(2)
)


CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)


SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1),
)
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    def _copyEventToForm(self, event, eventForm):
        """
        Generic method to copy events (so far conferences and sessions) into
        their equivalent form
        """
        for field in eventForm.all_fields():
            if hasattr(event, field.name):
                # convert Date to date string; just copy others
                if field.name.lower().endswith('date') or \
                        field.name.lower().endswith('time'):
                    setattr(eventForm, field.name,
                            str(getattr(event, field.name)))
                else:
                    setattr(eventForm, field.name, getattr(event, field.name))
            elif field.name == "websafeKey":
                setattr(eventForm, field.name, event.key.urlsafe())
        return eventForm

    def _get_user(self):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        return user

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = self._copyEventToForm(conf, ConferenceForm())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sf = self._copyEventToForm(session, SessionForm())
        sf.check_initialized()
        return sf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = self._get_user()
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                            for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']
        # add default values for those missing (both data model & outbound Message)
        for df in CONFERENCE_DEFAULTS:
            if data[df] in (None, []):
                data[df] = CONFERENCE_DEFAULTS[df]
                setattr(request, df, CONFERENCE_DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request

    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        # preload necessary data items
        user = self._get_user()

        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']

        # add default values for those missing (both data model & outbound Message)
        for sf in SESSION_DEFAULTS:
            if data[sf] in (None, []):
                data[sf] = SESSION_DEFAULTS[sf]
                setattr(request, sf, SESSION_DEFAULTS[sf])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'][:5], "%H:%M").time()
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
        #if data['typeOfSession']:
        #    data['typeOfSession'] = data['typeOfSession'].name

        # ID based on Conference key get Session key from ID
        c_key = ndb.Key(urlsafe=request.conferenceId)
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key
        # in terms of computational cost this is the best time to calculate
        # the featured speaker, as we don't need to calculate which is the
        # newest session
        featuredSpeaker = None
        user_profile = self._getProfileFromUser()
        if user_profile.mainEmail != request.speakerUserId:
            raise endpoints.InternalServerErrorException(
                "Speaker email must match authorized user")
        if self._isNewFeaturedSpeaker(user_profile,
                                      request.conferenceId):
            featuredSpeaker = getUserId(self._get_user())
        self._do_create_session(
            data, s_key.urlsafe(), ndb.Key(urlsafe=request.conferenceId).get(),
            featuredSpeaker=featuredSpeaker
        )
        return request

    def _isNewFeaturedSpeaker(self, profile, conferenceId):
        # this method is supposed to be called during a session creation, just
        # before persisting the data. This way the code in the transaction
        # _do_create_session does not get too big.
        # 1- get sessions from a particular profile in that conference
        # 2- If it has at least one, set as new featured speaker (added to the
        # session which is about to be created it will have at least two)
        if len(self._sessionsAsSpeaker(conferenceId, profile)) >= 1:
            return True
        return False

    @ndb.transactional()
    def _do_create_session(self, session_data, session_id, conference,
                           featuredSpeaker=None):
        conference.sessionIds.append(str(session_id))
        if featuredSpeaker:
            conference.featuredSpeaker = featuredSpeaker
        conference.put()
        Session(**session_data).put()

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user_id = getUserId(self._get_user())

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = self._getConference(request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = self._getConference(request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user_id = getUserId(self._get_user())

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = self._get_user()

        # get Profile from datastore
        p_key = ndb.Key(Profile, getUserId(user))
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key=p_key,
                displayName=user.nickname(),
                mainEmail=user.email(),
                teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
                sessionWishlist=[]

            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = self._getConference(wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city=="London")
        q = q.filter(Conference.topics=="Medical Innovations")
        q = q.filter(Conference.month==6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

    ########################################################################
    ################################# New code #############################
    ########################################################################

    def _getConference(self, urlsafeKey):
        conference = ndb.Key(urlsafe=urlsafeKey).get()
        if not conference:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % urlsafeKey)

    def _sessionsInConference(self, websafeConferenceKey):
        # returns a list with the sessions of that conference
        conference = self._getConference(websafeConferenceKey)
        return [ndb.Key(urlsafe=k).get() for k in conference.sessionIds]

    @endpoints.method(CONF_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessions',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """ Given a conference, return all its sessions """
        return SessionForms(items=[self._copySessionToForm(s) for s in
            self._sessionsInConference(request.websafeConferenceKey)])

    @endpoints.method(CONF_TYPE_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessionsByType/{sessionType}',
            http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """ Given a conference, return all sessions of a specified type
        (eg lecture, keynote, workshop) """

        conference, session_type = request.websafeConferenceKey,\
                                   request.sessionType
        q = Session.query()
        q = q.filter(Session.conferenceId == conference)
        q = q.filter(Session.typeOfSession == TypeOfSession(session_type))
        return SessionForms(items=[self._copySessionToForm(s) for s in q])

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='profile/getSessions',
            http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """ Given a speaker, return all sessions given by this particular
        speaker, across all conferences """

        q = Session.query()
        profile = self._getProfileFromUser()
        q = q.filter(Session.speakerUserId == profile.key.id())
        return SessionForms(items=[self._copySessionToForm(s) for s in q])

    @endpoints.method(SessionForm, SessionForm, path='session',
            http_method='POST', name='createSession')
    def createSession(self, sessionForm):
        return self._createSessionObject(sessionForm)

    def _sessionsAsSpeaker(self, websafeConferenceKey, profile):
        # returns in which sessions the user has been a speaker for that conf
        sessions = self._sessionsInConference(websafeConferenceKey)
        return [s for s in sessions if s.speakerUserId == profile.key.id()]

    @endpoints.method(SESSION_GET_REQUEST, SessionForm,
            path='profile/wishlist/{websafeSessionKey}',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """ Adds a session to the user wishlist """
        key = request.websafeSessionKey
        profile = self._getProfileFromUser()
        if not getattr(profile, 'sessionWishList', None):
            profile.sessionWishlist = [key]
        else:
            profile.sessionWishlist.append(key)
        profile.put()
        return self._copySessionToForm(ndb.Key(urlsafe=key).get())

    @endpoints.method(CONF_GET_REQUEST, SessionForms,
            path='profile/wishlist/{websafeConferenceKey}',
            http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """ Returns the user wishlist for a specific conference """
        conferenceId = request.websafeConferenceKey
        profile = self._getProfileFromUser()
        sessions = [ndb.Key(urlsafe=s).get() for s in profile.sessionWishlist]
        return SessionForms(items=[self._copySessionToForm(s) for s in sessions
                                   if s.conferenceId == conferenceId])

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='filterPlayground/after7',
            http_method='GET', name='sessionsAfter7pm')
    def sessionsAfter7pm(self, request):
        """ Returns all non-workshop sessions that take place after 7pm.
        Datastore will not allow two inequality filters in two different
        properties, so the way to fix it is to do two simple queries
        (all sessions after 7 and all workshops after 7) and substract one to
        the other.
        """
        # workshops after 7pm
        q1 = Session.query()
        q1 = q1.filter(Session.startTime > time(19, 0, 0))
        q1 = q1.filter(Session.typeOfSession == TypeOfSession.WORKSHOP)
        # all sessions after 7pm
        q2 = Session.query()
        q2 = q2.filter(Session.startTime > time(19, 0, 0))
        s1, s2 = [s for s in q1], [s for s in q2]
        # the statement below won't work because app engine does not implement
        # the __hash__ method, so sets cannot be created.
        #result = set([s for s in q2]).difference(set([s for s in q1]))
        result = [s for s in s2 if s not in s1]
        return SessionForms(items=[self._copySessionToForm(s) for s in result])

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground/moleConferences',
            http_method='GET', name='moleConferences')
    def moleConferences(self, request):
        """ Returns conferences with sessions not longer than 60 minutes
        that contain moles in the highlights """
        q = Session.query()
        q = q.filter(Session.highlights == 'moles')
        q = q.filter(Session.duration < 60)

        conferences = ndb.get_multi([ndb.Key(urlsafe=s.conferenceId) for s in q])
        # I wish I didn't have to do this,but datastore is returning duplicates
        # and google won't tell me why. Also, __hash__ raises an exception,
        # so it is not possible to convert the list into a set to remove
        # duplicates more efficiently
        non_repeated = []
        for c in conferences:
            if c not in non_repeated:
                non_repeated.append(c)
        return ConferenceForms(
            items=[self._copyConferenceToForm(c, "") for c in non_repeated]
        )

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground/londonAttendees',
            http_method='GET', name='londonAttendees')
    def londonAttendees(self, request):
        """ Returns conferences in London with more than 1000 attendees """
        q = Conference.query()
        q = q.filter(Conference.city == 'London').\
            filter(Conference.maxAttendees > 1000)
        return ConferenceForms(
            items=[self._copyConferenceToForm(c, "") for c in q]
        )


api = endpoints.api_server([ConferenceApi]) # register API

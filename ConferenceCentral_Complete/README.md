App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.

## Work done

> App Architechture

All the implementation attempts to follow the same guidelines provided in the Conference Central app.
No class has been added to represent a speaker due to lack of available time.

> App Model

The **Profile** representation has changed as follows:
A **SessionWishlist** attribute has been added. This represents a list of unique Session keys that the user has added to his wishlist.

A **TypeOfSession** enum class has been added to represent the different types of sessions in a controlled way.

The **Session** representation has been added as follows:
 After having a look at the requirements these were the attributes added
 * **name**: session name
 * **highlights**: list of session highlights
 * **speakerUserId**: speaker's email
 * **duration**: session duration in minutes
 * **typeOfSession**: enum value (see explanation for TypeOfSession above)
 * **date**: session's date
 * **startTime**: session's start time
 * **conferenceId**: reference to the conference it belongs to. I have been told in the code review that given the conference is the parent object this attribute might be redundant, and it looks like it. I will definitely take it into account for my next app engine project!

> Add Sessions to a Conference

All the requested methods have been created. Also, since Conference and Session creations do not differ that much, some common functionality has been refactored into _copyEventToForm, which simplifies both _copyConferenceToForm and _copySessionToForm

> Add Sessions to User Wishlist

Both requested methods have been added.

> Work on indexes and queries

Two methods have been added to work on queries, each of them requires a new composite index.
 - The first one gets all Conferences with Sessions no longer than 1 hours which include the word moles in the highlights.
 - The second one returns all Conferences that take place in London and have more than 1000 attendees.

About the query related problem regarding non-workshops after 7pm, it cannot be done in a single query because Datastore does not allow two or more inequality filters in different properties. I fixed the problem by dividing the query into two simpler queries and then calculate the difference between them:
 all sessions after 7pm - workshops after 7pm

> Define the following endpoints method: getFeaturedSpeaker()

To implement this feature with a task I created a task that gets run every time a Session is created. This task will check if the new session's speaker is the new featured one. If that's the case a memcache announcement will be modified to set the data accordingly.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool

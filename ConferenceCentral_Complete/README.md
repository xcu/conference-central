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

All the implementation attempts to follow the same guidelines provided in the Conference Central app. Regarding the model, most of the fields are straight forward. I added a couple of comments to justify a specific type, but other than that it aims to be self explanatory.
No class has been added to represent a speaker due to lack of available time, but that addition could have probably solved the restriction mentioned in the getFeaturedSpeaker section.

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

There are probably several approaches to implement this. I preferred to add a new attribute in the Conference kind and calculate it only once, when a new session is created. This way, if we have 1000 users requesting the featured speaker at the same time we will not have to calculate the same thing 1000 times, only to return an attribute that has been calculated already.
Also, session creation requires the speaker email to be the same as the authorized user, since we need the User.key to fetch the Profile or build a new one. According to app engine docs the User class represents an authorized user, thereby the restriction.

[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool

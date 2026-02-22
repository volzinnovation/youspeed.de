# youspeed.de
## Summary
Data + Camera driven speed sign recognition with traffic fine calculation

## Project Description
This project shall create an iphone app that is able to recognize traffic signs (speed signs only) based on a suitable available vision neural network that is used to process the camera video feed and recognize speed signs detected on the video stream. The recognized speed limit is displayed to the user using the official traffic sign symbol for the respective speed in Germany,additionally the fine of driving faster than the allowed speed is calculated by official German traffic regulations and displayed to the user. User can pick warning levels (above speed limit or amount of fines) in the settings, and choose from visual and auditory warnings.

The recognized speed limits should be saved to a database, locally for the user and later in a global (online) database. The local database is augmented with the traffic sign information that is available in OpenStreetMap (see https://wiki.openstreetmap.org/wiki/Key:maxspeed ) hence a batch job is necessary to bootstrap this second database from a country PBF,we start with Germany.

While driving and using the app, the user geolocation is mapped to the appropriate ways from Openstreetmap to identify the existing speed limits. In addition general speed limits while driving on a certain type of way (e.g. Landstrasse maximum 100) should be considered based on German traffic rules. Also when driving within city limits the usual speed limit of 50 should be the default, so app needs to identify whether geolocation of user is within a certain city boundary. 

To test the app we want to start with a small region in particular https://download.geofabrik.de/europe/germany/baden-wuerttemberg/karlsruhe-regbez-latest.osm.pbf

User should be able to confirm a newly detected limit in a easy way while driving, e.g. through a speech command and voice interaction with the app.

Come up with a research on German traffic rules and an implementation plan before actually generating code



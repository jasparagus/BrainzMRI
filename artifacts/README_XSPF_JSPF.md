# Playlist Formatting
Defines playlist formats.

## XSPF
A simple example looks like this:

```
<?xml version="1.0" encoding="UTF-8"?>
<playlist version="1" xmlns="http://xspf.org/ns/0/">
  <trackList>
    <track><location>file:///music/song\_1.ogg</location></track>
    <track><location>file:///music/song\_2.flac</location></track>
    <track><location>file:///music/song\_3.mp3</location></track>
  </trackList>
</playlist>
or this:

<?xml version="1.0" encoding="UTF-8"?>
<playlist version="1" xmlns="http://xspf.org/ns/0/">
  <trackList>
     <track><location>http://example.net/song\_1.ogg</location></track>
     <track><location>http://example.net/song\_2.flac</location></track>
     <track><location>http://example.com/song\_3.mp3</location></track>
   </trackList>
 </playlist>
```
 
 
 
## JSPF (Standard)
JSPF is JSON XSPF. The definitions of JSPF fields follow from the XSPF specification, but the expression uses Javascript.

This is documented by example, per the JSON below. The example below was engineered by (in order of how many contributions they made) Sebastian Pipping, Chris Anderson and Ivo Emanuel Gonçalves.

A simplified version, without the full range of features:

```
 {
   "playlist" : {
     "title"         : "Two Songs From Thriller", // name of the playlist
     "creator"       : "MJ Fan", // name of the person who created the playlist
     "track"         : [
       {
         "location"      : ["http://example.com/billiejean.mp3"], 
         "title"         : "Billie Jean",
         "creator"       : "Michael Jackson",
         "album"         : "Thriller"
       }, 
       {
       "location"      : ["http://example.com/thegirlismine.mp3"], 
       "title"         : "The Girl Is Mine",
       "creator"       : "Michael Jackson",
       "album"         : "Thriller"
       }
     ]
   }
 }
```

Comprehensive example:

```
 {
   "playlist" : {
     "title"         : "JSPF example",
     "creator"       : "Name of playlist author",
     "annotation"    : "Super playlist",
     "info"          : "http://example.com/",
     "location"      : "http://example.com/",
     "identifier"    : "http://example.com/",
     "image"         : "http://example.com/",
     "date"          : "2005-01-08T17:10:47-05:00",
     "license"       : "http://example.com/",
     "attribution"   : [
       {"identifier"   : "http://example.com/"},
       {"location"     : "http://example.com/"}
     ],
     "link"          : [
       {"http://example.com/rel/1/" : "http://example.com/body/1/"},
       {"http://example.com/rel/2/" : "http://example.com/body/2/"}
     ],
     "meta"          : [
       {"http://example.com/rel/1/" : "my meta 14"},
       {"http://example.com/rel/2/" : "345"}
     ],
     "extension"     : {
       "http://example.com/app/1/" : [ARBITRARY_EXTENSION_BODY, ARBITRARY_EXTENSION_BODY],
       "http://example.com/app/2/" : [ARBITRARY_EXTENSION_BODY]
     },
     "track"         : [
       {
         "location"      : ["http://example.com/1.ogg", "http://example.com/2.mp3"],
         "identifier"    : ["http://example.com/1/", "http://example.com/2/"],
         "title"         : "Track title",
         "creator"       : "Artist name",
         "annotation"    : "Some text",
         "info"          : "http://example.com/",
         "image"         : "http://example.com/",
         "album"         : "Album name",
         "trackNum"      : 1,
         "duration"      : 0,
         "link"          : [
           {"http://example.com/rel/1/" : "http://example.com/body/1/"},
           {"http://example.com/rel/2/" : "http://example.com/body/2/"}
         ],
         "meta"          : [
           {"http://example.com/rel/1/" : "my meta 14"},
           {"http://example.com/rel/2/" : "345"}
         ],
         "extension"     : {
           "http://example.com/app/1/" : [ARBITRARY_EXTENSION_BODY, ARBITRARY_EXTENSION_BODY],
           "http://example.com/app/2/" : [ARBITRARY_EXTENSION_BODY]
         }
       }
     ]
   }
 }
```


## ListenBrainz JSPF
ListenBrainz uses JSPF for playlist transport (importing/exporting playlists, in the API, and internally between web servers and client browser sessions). A number of extra fields are required that are not part of standard JSPF/XSPF; these define two extensions to JSPF. The proposed format example is here:

```
{
   "playlist" : {
      "extension" : {
         "https://musicbrainz.org/doc/jspf#playlist" : {
            "created_for" : "Mr_Monkey",
            "creator" : "troi-bot",
            "collaborators" : [
               "rob",
               "alastairp",
               "zas"
            ],
            "copied_from" : "https://listenbrainz.org/playlist/9dae92c5-c98e-4e7e-9c15-8b6d32607aed",
            "copied_from_deleted": true,
            "public" : true,
            "last_modified_at": "2020-11-27T10:45:49+00:00",
            "additional_metadata": { . . . } 
         }
      },
      "creator" : "ListenBrainz Troi",
      "date" : "2005-01-08T17:10:47-05:00",
      "title" : "1980s flashback jams",
      "track" : [
         {
            "title" : "Gold",
            "identifier" : "https://musicbrainz.org/recording/e8f9b188-f819-4e43-ab0f-4bd26ce9ff56",
            "creator" : "Spandau Ballet",
            "extension" : {
               "https://musicbrainz.org/doc/jspf#track" : {
                  "added_by" : "zas",
                  "artist_identifiers" : [
                     "https://musicbrainz.org/artist/4c0d9acf-a8a1-4765-9c56-05f92f68c048"
                  ],
                  "added_at" : "2020-11-27T10:45:49+00:00",
                  "release_identifier" : "https://musicbrainz.org/release/8d3acbb4-c541-4324-a124-a670615f0f77",
                  "additional_metadata": { 
                     "subsonic_id": "e66f7f91-2884-4cdf-97b3-24faee6be03e"
                  } 
               }
            },
            "album" : "True"
         }
      ],
      "identifier" : "https://listenbrainz.org/playlist/7f4cf4d3-f5ca-453a-b5c8-00e8a30a9bac"
   }
}
```

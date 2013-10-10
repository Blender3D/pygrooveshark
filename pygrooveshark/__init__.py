import os
import sys

import itertools
import datetime
import requests
import hashlib
import json
import uuid
import time
import re

from pygrooveshark import utils

USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 6_0 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Version/6.0 Mobile/10A5376e Safari/8536.25'
BASE_URL = 'https://html5.grooveshark.com'
API_URL = BASE_URL + '/more.php?'
VALID_RESOURCE_SIZES = [20, 30, 40, 50, 70, 80, 90, 120, 142, 200, 500]

class CoverArtMixin:
    def cover_art_url(self, size=500, search_parents=True):
        if size not in VALID_RESOURCE_SIZES:
            raise ValueError('Invalid size. Must be one of: ' + ', '.join(map(str, VALID_RESOURCE_SIZES)))
        elif self.cover_art_filename:
            if self.__class__ is Song:
                name = 'album'
            else:
                name = self.__class__.__name__.lower()

            return 'http://images.gs-cdn.net/static/{0}s/{1}_{2}'.format(name, size, self.cover_art_filename)
        elif search_parents and hasattr(self, 'parent'):
            return getattr(self, self.parent).cover_art_url(size)

class Artist(CoverArtMixin, object):
    def __init__(self, id, name=None):
        self.id = id
        self.name = name
        self.cover_art_filename = None

    @classmethod
    def from_dict(cls, d):
        i = cls(d['ArtistID'], d['ArtistName'])
        i.cover_art_filename = None if d['ArtistCoverArtFilename'] == '0' else d['ArtistCoverArtFilename']

        return i

class Album(CoverArtMixin, object):
    parent = 'artist'

    def __init__(self, id, name=None):
        self.id = id
        self.name = name
        self.cover_art_filename = None

        self.artist = None

    @classmethod
    def from_dict(cls, d):
        i = cls(d['AlbumID'], d['AlbumName'])

        if 'AlbumCoverArtFilename' in d:
            i.cover_art_filename = None if d['AlbumCoverArtFilename'] == '0' else d['AlbumCoverArtFilename']

        return i


class Song(CoverArtMixin, object):
    parent = 'album'

    def __init__(self, id, name=None):
        self.id = id
        self.name = name

        self.album = None

    @classmethod
    def from_dict(cls, d):
        if 'SongName' in d:
            i = cls(d['SongID'], d['SongName'])
        else:
            i = cls(d['SongID'], d['Name'])

        i.artist = Artist.from_dict(d)
        i.album = Album.from_dict(d)
        i.album.artist = i.artist

        i.year = int(d['Year'])
        i.added_on = datetime.datetime.fromtimestamp(float(d['TSAdded']))
        i.score = d['Score']
        i.raw_score = d['RawScore']
        i.popularity = d['Popularity']
        i.popularity_index = d['PopularityIndex']
        i.is_verified = d['IsVerified'] == '1'
        i.is_low_bitrate_available = d['IsLowBitrateAvailable'] == '1'
        i.track_num = int(d['TrackNum'])
        i.flags = d['Flags']
        i.duration = datetime.timedelta(seconds=float(d['EstimateDuration']))
        i.average_duration = float(d['AvgDuration'])
        i.average_rating = float(d['AvgRating'])

        i.cover_art_filename = None if d['CoverArtFilename'] == '0' else d['CoverArtFilename']

        return i

    def __str__(self):
        return '<Song {self.id} "{self.name}" by "{self.artist.name}">'.format(self=self)

class GroovesharkClient(object):
    def __init__(self):
        self.connection = requests.Session()
        self.connection.headers = {
            'User-Agent': USER_AGENT
        }

        self.config = self._get_config()
        self.uuid = str(uuid.uuid4())

        self.token = None
        self.token_time = 0

        self._get_client_info()

    def _get_config(self):
        response = self.connection.get(BASE_URL).text.splitlines()

        for line in response:
            if line.lstrip().startswith('GS.config ='):
                data = line.split('GS.config =', 1)[1].strip(' ;()')
                break
        else:
            raise ValueError('Invalid HTML response')

        return json.loads(data)

    def _get_client_info(self):
        data = self.connection.get(BASE_URL + '/build/app.min.js').text
        self.revision_token = re.findall(r'var n="([a-z]+)"', data, flags=re.I)[0]
        self.client, self.client_revision = re.findall(r'client:"(.*?)",clientRevision:"(.*?)"', data)[0]

    def request(self, method, **kwargs):
        header = {
            'client': self.client,
            'clientRevision': self.client_revision,
            'privacy': 0,
            'country': self.config['country'],
            'uuid': self.uuid,
            'session': self.config['sessionID']
        }

        if method not in ['getCommunicationToken', 'initiateSession', 'getServiceStatus']:
            if time.time() - self.token_time > 15 * 10**5:
                self.getCommunicationToken()

            rand = utils.random_hex()
            nonce = ':'.join([method, self.token, self.revision_token, rand])

            header['token'] = rand + hashlib.sha1(nonce).hexdigest()

        return self.connection.post(API_URL + method, data=json.dumps({
            'header': header,
            'method': method,
            'parameters': kwargs
        })).json()['result']

    def getCommunicationToken(self):
        self.token = self.request('getCommunicationToken', secretKey=hashlib.md5(self.config['sessionID']).hexdigest())
        self.token_time = time.time()

    def search(self, query, songs=True, playlists=False, albums=False):
        result = self.request('getResultsFromSearch',
            guts=0,
            ppOverride='',
            query=query,
            type=['Songs'] * songs + ['Playlists'] * playlists + ['Albums'] * albums
        )

        for song in result['result']['Songs']:
            yield Song.from_dict(song)

    def getStreamKey(self, id):
        return self.request('getStreamKeyFromSongIDEx',
            country=self.config['country'],
            mobile=True,
            prefetch=False,
            songID=id
        )

    def getLibrary(self, user_id):
        for page in itertools.count():
            response = self.request('userGetSongsInLibrary',
                userID=user_id,
                page=page
            )

            for song in response['Songs']:
                song['SongName'] = song['Name']
                yield song

            if not response['hasMore']:
                break

    def getFavorites(self, user_id, what='songs'):
        response = self.request('getFavorites',
            userID=user_id,
            ofWhat=what.title()
        )

        for song in response:
            song['SongName'] = song['Name']
            yield song

    def favorite(self, item):
        return self.request('favorite',
            ID=item.id,
            what=item.__class__.__name__
        )['success']

    def unfavorite(self, item):
        return self.request('favorite',
            ID=item.id,
            what=item.__class__.__name__
        )['success']

    def userAddSongsToLibrary(self, songs):
        return self.request('addSongsToLibrary',
            songs=[{
                'songID': song.id,
                'songName': song.name,
                'track': song.track,
                'artFilename': song.cover_art_filename,
                'isVerified': int(song.is_verified),
                'albumID': song.album.id,
                'albumName': song.album.name,
                'artistID': song.artist.id,
                'artistName': song.artist.name,
                'token': None
            } for song in songs]
        )['success']

    def userRemoveSongsFromLibrary(self, songs):
        return self.request('userRemoveSongsFromLibrary',
            userID=self.user_info['userID'],
            songIDs=[song.id for song in songs],
            albumIDs=[song.album.id for song in songs],
            artistIDs=[song.artist.id for song in songs]
        )['success']

    def login(self, username, password):
        response = self.request('authenticateUser',
            username=username,
            password=password
        )

        if not response['authToken']:
            raise ValueError('Invalid username or password')

        self.auth_token = response['authToken']
        self.user_info = response

    def getStreamURL(self, song):
        info = self.getStreamKey(song.id)

        return 'http://' + info['ip'] + '/stream.php?streamKey=' + info['streamKey']

    def downloadSongs(self, songs):
        for song in songs:
            filename = utils.windows_filename(song.album.name + ' - ' + songname + '.mp3')
            path = os.path.join(sys.argv[2], filename)

            if os.path.exists(path):
                print 'Skipping', repr(filename)
                continue

            print 'Downloading', repr(filename)

            url = self.getStreamURL(song.id)

            with open(path, 'wb') as handle:
                request = self.connection.get(url, stream=True)

                for chunk in request.iter_content(1024 * 10):
                    if not chunk:
                        break

                    handle.write(chunk)

            print 'Downloaded', repr(filename)


if __name__ == '__main__':
    client = GroovesharkClient()

    song = Song(26108775)
    print client.getStreamURL(song)
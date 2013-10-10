import os
import sys

import itertools
import requests
import hashlib
import random
import string
import json
import uuid
import time
import re

USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 6_0 like Mac OS X) AppleWebKit/536.26 (KHTML, like Gecko) Version/6.0 Mobile/10A5376e Safari/8536.25'
BASE_URL = 'https://html5.grooveshark.com'
API_URL = BASE_URL + '/more.php?'

def random_hex():
    return ''.join(random.choice(string.hexdigits) for n in xrange(6))

def windows_filename(filename):
    return re.sub(r'[/\\:*?"<>|]', '', filename)

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

            rand = random_hex()
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
            yield song

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

    def getStreamURL(self, song_id):
        info = self.getStreamKey(song_id)

        return 'http://' + info['ip'] + '/stream.php?streamKey=' + info['streamKey']

    def downloadSongs(self, songs):
        for song in songs:
            filename = windows_filename(song['AlbumName'] + ' - ' + song['SongName'] + '.mp3')
            path = os.path.join(os.path.expanduser('~/Music/Grooveshark'), filename)

            if os.path.exists(path):
                print 'Skipping', repr(filename)
                continue

            print 'Downloading', repr(filename)

            url = self.getStreamURL(song['SongID'])

            with open(path, 'wb') as handle:
                request = self.connection.get(url, stream=True)

                for chunk in request.iter_content(1024 * 10):
                    if not chunk:
                        break

                    handle.write(chunk)

            print 'Downloaded', repr(filename)


if __name__ == '__main__':
    client = GroovesharkClient()

    songs = client.getFavorites(sys.argv[1])
    client.downloadSongs(songs)
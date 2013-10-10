# Grooveshark Downloader

It downloads all of your favorited songs into a folder and saves them as *album name - song name.mp3*.

## Usage

    $ python main.py <your_user_id> ~/Music/Grooveshark

## Getting your user id

Sniff the requests sent by Grooveshark. Most of those have it in the sent JSON. You can also get it out of your profile picture URL:

    http://images.gs-cdn.net/static/users/40_12345678.jpg

Here, `12345678` is your user id.

## It's broken

I wrote it in an hour and a half and it works for me. The code is somewhat readable, so send a pull request if you find something terribly broken.

# corostc

Web-based API and command-line clients
for [Coros Training Center](https://training.coros.com).

## Application authorization

Coros TC doesn't seem to allow more than one simultaneous login session for
a given user; using the CLI will logout a web browser session, and vice
versa.

The way around this is to login on the web browser, copy the `CPL-coros-token`
cookie, and then use this token to make the command-line client appear to be
the "same" session (via `-T`/`--accesstoken` option)

# License

[GPL v3 or later](http://www.gnu.org/copyleft/gpl.html)

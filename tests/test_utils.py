"""
Copyright (c) 2015 Red Hat, Inc
All rights reserved.

This software may be modified and distributed under the terms
of the BSD license. See the LICENSE file for details.
"""
from flexmock import flexmock
import os
import os.path
import pytest
import datetime
import sys
from time import tzset

from osbs.utils import (buildconfig_update,
                        get_imagestreamtag_from_image,
                        git_repo_humanish_part_from_uri,
                        get_time_from_rfc3339, strip_registry_from_image,
                        TarWriter, TarReader, make_name_from_git,
                        get_instance_token_file_name, Labels)
from osbs.exceptions import OsbsException
import osbs.kerberos_ccache


def test_buildconfig_update():
    x = {'a': 'a', 'strategy': {'b1': 'B1', 'b2': 'B2', 'b11': {'x': 'y'}}, 'd': 'D'}
    y = {'a': 'A', 'strategy': {'b1': 'newB1', 'b3': 'B3', 'b11': {}}, 'c': 'C'}
    buildconfig_update(x, y)
    assert x == {'a': 'A', 'strategy': {'b1': 'newB1', 'b3': 'B3', 'b11': {}}, 'c': 'C', 'd': 'D'}


@pytest.mark.parametrize(('uri', 'humanish'), [
    ('http://git.example.com/git/repo.git/', 'repo'),
    ('http://git.example.com/git/repo.git', 'repo'),
    ('http://git.example.com/git/repo/.git', 'repo'),
    ('git://hostname/path', 'path'),
])
def test_git_repo_humanish_part_from_uri(uri, humanish):
    assert git_repo_humanish_part_from_uri(uri) == humanish


@pytest.mark.parametrize(('img', 'expected'), [
    ('fedora23', 'fedora23'),
    ('fedora23:sometag', 'fedora23:sometag'),
    ('fedora23/python', 'fedora23/python'),
    ('fedora23/python:sometag', 'fedora23/python:sometag'),
    ('docker.io/fedora23', 'fedora23'),
    ('docker.io/fedora23/python', 'fedora23/python'),
    ('docker.io/fedora23/python:sometag', 'fedora23/python:sometag'),
])
def test_strip_registry_from_image(img, expected):
    assert strip_registry_from_image(img) == expected


@pytest.mark.parametrize(('img', 'expected'), [
    ('fedora23', 'fedora23:latest'),
    ('fedora23:sometag', 'fedora23:sometag'),
    ('fedora23/python', 'fedora23-python:latest'),
    ('fedora23/python:sometag', 'fedora23-python:sometag'),
    ('docker.io/fedora23', 'fedora23:latest'),
    ('docker.io/fedora23/python', 'fedora23-python:latest'),
    ('docker.io/fedora23/python:sometag', 'fedora23-python:sometag'),
])
def test_get_imagestreamtag_from_image(img, expected):
    assert get_imagestreamtag_from_image(img) == expected


@pytest.mark.parametrize('tz', [
    'UTC',
    'EST',
])
@pytest.mark.parametrize(('rfc3339', 'seconds'), [
    ('2015-08-24T10:41:00Z', 1440412860.0),
])
def test_get_time_from_rfc3339_valid(rfc3339, seconds, tz):
    os.environ['TZ'] = tz
    tzset()
    assert get_time_from_rfc3339(rfc3339) == seconds


@pytest.mark.parametrize(('repo', 'branch', 'limit', 'separator', 'expected'), [
    ('spam', 'bacon', 10, '-', 'spam-bacon'),
    ('spam', 'bacon', 5, '-', 'sp-ba'),
    ('spam', 'bacon', 10, '*', 'spam*bacon'),
    ('spammmmmm', 'bacon', 10, '-', 'spamm-baco'),
    ('spam', 'baconnnnnnn', 10, '-', 'spam-bacon'),
    ('s', 'bacon', 10, '-', 's-bacon'),
    ('spam', 'b', 10, '-', 'spam-b'),
    ('spam', 'bacon', 10, '^^^', 'spam^^^bac'),
    ('spam', '', 10, '-', 'spam-unkno'),
    ('spam', 'baco-n', 10, '-', 'spam-baco-'),
    ('spam', 'ba---n', 10, '-', 'spam-ba---'),
    ('spam', '-----n', 10, '-', 'spam------'),
    ('https://github.com/blah/spam.git', 'bacon', 10, '-', 'spam-bacon'),
])
def test_make_name_from_git(repo, branch, limit, separator, expected, hash_size=5):
    bc_name = make_name_from_git(repo, branch, limit + len(separator) + hash_size, separator, hash_size=hash_size)

    assert expected == bc_name[:-(hash_size + len(separator))]

def test_make_name_from_git_collide():
    bc1 = make_name_from_git("very_log_repo name_first", "also_long_branch_name", 30, '-')
    bc2 = make_name_from_git("very_log_repo name_second", "also_long_branch_name", 30, '-')
    assert bc1 != bc2

@pytest.mark.skipif(sys.version_info[0] < 3,
                    reason="requires python3")
@pytest.mark.parametrize('tz', [
    'UTC',
    'EST',
])
@pytest.mark.parametrize(('rfc3339', 'seconds'), [
    # These tests only work in Python 3
    ('2015-08-24T10:41:00.1Z', 1440412860.1),
    ('2015-09-22T11:12:00+01:00', 1442916720),
])
def test_get_time_from_rfc3339_valid_alt_format(rfc3339, seconds, tz):
    os.environ['TZ'] = tz
    tzset()
    assert get_time_from_rfc3339(rfc3339) == seconds


@pytest.mark.parametrize('rfc3339', [
    ('just completely invalid'),
])
def test_get_time_from_rfc3339_invalid(rfc3339):
    with pytest.raises(ValueError):
        get_time_from_rfc3339(rfc3339)


KLIST_TEMPLATE = """
Ticket cache: FILE:/tmp/krb5cc_1000
Default principal: user@REDBAT.COM

Valid starting     Expires            Service principal
08/11/15 08:43:56  %m/%d/%y %H:%M:%S  krbtgt/REDBAT.COM@REDBAT.COM
08/11/15 14:13:19  08/12/15 00:13:14  imap/gmail.org@REDBAT.COM
"""

KEYTAB_PATH = '/etc/keytab'
CCACHE_PATH = '/tmp/krb5cc_thing'
PRINCIPAL = 'prin@IPAL'


@pytest.mark.parametrize("custom_ccache", [True, False])
def test_kinit_nocache(custom_ccache):
    flexmock(osbs.kerberos_ccache).should_receive('run') \
                                  .with_args(['klist'], extraenv=object) \
                                  .and_return(1, "", "") \
                                  .once()
    flexmock(osbs.kerberos_ccache).should_receive('run') \
                                  .with_args(['kinit', '-k', '-t',
                                              KEYTAB_PATH, PRINCIPAL],
                                             extraenv=object) \
                                  .and_return(0, "", "") \
                                  .once()
    flexmock(os.environ).should_receive('__setitem__') \
                        .with_args("KRB5CCNAME", CCACHE_PATH) \
                        .times(1 if custom_ccache else 0)

    osbs.kerberos_ccache.kerberos_ccache_init(PRINCIPAL, KEYTAB_PATH,
                                              CCACHE_PATH if custom_ccache else None)


@pytest.mark.parametrize("custom_ccache", [True, False])
def test_kinit_recentcache(custom_ccache):
    yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
    klist_out = yesterday.strftime(KLIST_TEMPLATE)

    flexmock(osbs.kerberos_ccache).should_receive('run') \
                                  .with_args(['klist'], extraenv=object) \
                                  .and_return(0, klist_out, "") \
                                  .once()
    flexmock(osbs.kerberos_ccache).should_receive('run') \
                                  .with_args(['kinit', '-k', '-t',
                                              KEYTAB_PATH, PRINCIPAL],
                                             extraenv=object) \
                                  .and_return(0, "", "") \
                                  .once()
    flexmock(os.environ).should_receive('__setitem__') \
                        .with_args("KRB5CCNAME", CCACHE_PATH) \
                        .times(1 if custom_ccache else 0)

    osbs.kerberos_ccache.kerberos_ccache_init(PRINCIPAL, KEYTAB_PATH,
                                              CCACHE_PATH if custom_ccache else None)


@pytest.mark.parametrize("custom_ccache", [True, False])
def test_kinit_newcache(custom_ccache):
    tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
    klist_out = tomorrow.strftime(KLIST_TEMPLATE)

    flexmock(osbs.kerberos_ccache).should_receive('run') \
                                  .with_args(['klist'], extraenv=object) \
                                  .and_return(0, klist_out, "") \
                                  .once()
    flexmock(osbs.kerberos_ccache).should_receive('run') \
                                  .with_args(['kinit', '-k', '-t',
                                              KEYTAB_PATH, PRINCIPAL],
                                             extraenv=object) \
                                  .never()
    flexmock(os.environ).should_receive('__setitem__') \
                        .with_args("KRB5CCNAME", CCACHE_PATH) \
                        .times(1 if custom_ccache else 0)

    osbs.kerberos_ccache.kerberos_ccache_init(PRINCIPAL, KEYTAB_PATH,
                                              CCACHE_PATH if custom_ccache else None)


@pytest.mark.parametrize("custom_ccache", [True, False])
def test_kinit_fails(custom_ccache):
    flexmock(osbs.kerberos_ccache).should_receive('run') \
                                  .with_args(['klist'], extraenv=object) \
                                  .and_return(1, "", "") \
                                  .once()
    flexmock(osbs.kerberos_ccache).should_receive('run') \
                                  .with_args(['kinit', '-k', '-t',
                                              KEYTAB_PATH, PRINCIPAL],
                                             extraenv=object) \
                                  .and_return(1, "error", "error") \
                                  .once()
    flexmock(os.environ).should_receive('__setitem__') \
                        .with_args("KRB5CCNAME", CCACHE_PATH) \
                        .never()

    with pytest.raises(OsbsException):
        osbs.kerberos_ccache.kerberos_ccache_init(PRINCIPAL, KEYTAB_PATH,
                                                  CCACHE_PATH if custom_ccache else None)


@pytest.mark.parametrize("prefix", ["", "some/thing"])
def test_tarfile(tmpdir, prefix):
    filename = str(tmpdir.join("archive.tar.bz2"))

    with TarWriter(filename, directory=prefix) as t:
        t.write_file("a/b.c", b"foobar")

    assert os.path.exists(filename)

    for f in TarReader(filename):
        assert f.filename == os.path.join(prefix, "a/b.c")
        content = f.fileobj.read()
        assert content == b"foobar"


def test_get_instance_token_file_name():
    expected = os.path.join(os.path.expanduser('~'), '.osbs', 'spam.token')

    assert get_instance_token_file_name('spam') == expected

@pytest.mark.parametrize(('labels', 'fnc', 'expect'), [
        ({},
         ("get_name", Labels.LABEL_TYPE_COMPONENT),
         "com.redhat.component"),
        ({},
         ("get_name", "doesnt_exist"),
         Exception),
        ({"Name" : "old",
          "name" : "new"},
         ("get_name", Labels.LABEL_TYPE_NAME),
         "name"),
        ({"Name" : "old"},
         ("get_name", Labels.LABEL_TYPE_NAME),
         "Name"),
        ({},
         ("get_new_names_by_old", None),
         {"Vendor": "vendor", "Name": "name", "Build_Host": "com.redhat.build-host",
          "Version": "version", "Architecture": "architecture",
          "Release": "release", "BZComponent": "com.redhat.component",
          "Authoritative_Registry": "authoritative-source-url"}),
        ({"Name" : "old",
          "name" : "new"},
         ("get_name_and_value", Labels.LABEL_TYPE_NAME),
         ("name", "new")),
        ({},
         ("get_name_and_value", Labels.LABEL_TYPE_NAME),
         KeyError),
        ({},
         ("get_name_and_value", "doest_exist"),
         Exception),
    ])
def test_labels(labels, fnc, expect):
    label = Labels(labels)

    fn, arg = fnc
    if isinstance(expect, type):
        with pytest.raises(expect):
            if arg is not None:
                assert getattr(label, fn)(arg) == expect
            else:
                assert getattr(label, fn)() == expect
    else:
        if arg is not None:
            assert getattr(label, fn)(arg) == expect
        else:
            assert getattr(label, fn)() == expect

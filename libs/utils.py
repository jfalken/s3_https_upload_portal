#!/usr/bin/env python

import base64
import hmac
import hashlib
import sys
import boto
import uuid
import string
import os
import json
import urllib2
import logging
from boto.s3.lifecycle import Lifecycle
from datetime import datetime
from datetime import timedelta
from boto.exception import S3ResponseError


def setup_logging():

    logging.basicConfig(filename='httpsdropbox.log',
                        format='[%(asctime)s] [%(levelname)s] - %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.INFO)
    return logging


def dt_to_string(dt):
    ''' converts a date time object to a string for pretty printing '''
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def init():
    ''' initialize the bucket'''

    try:
        ak, sk = get_env_creds()
        bucket_name = os.environ['BUCKET']
        if '.' in bucket_name:
            print ('WARNING: You will get SSL errors with a "." '
                   'in a bucket name - this is because the bucket name will'
                   ' appear as a subdomain of amazon. We highly encourage you'
                   ' to chose a bucket name without a dot in it')
        s3 = boto.connect_s3(aws_access_key_id=ak,
                             aws_secret_access_key=sk)
        bucket = s3.get_bucket(bucket_name)
        bucket.configure_versioning(True)
    except S3ResponseError:
        # bucket doesn't exist, let's create it
        bucket = s3.create_bucket(bucket_name)
        bucket.configure_versioning(True)
    except:
        print 'Could not create bucket: Error: %s' % (str(sys.exc_info()))
        raise

    # upload all the static resources (js, css) and make public
    try:
        k = boto.s3.key.Key(bucket)
        for prefix in ['', 'upload_forms/']:
            files = getFilePaths('static')
            for f in files:
                key = prefix + str(f)
                if not bucket.get_key(key):
                    k.key = key
                    k.set_contents_from_filename(f)
                    k.make_public()
    except S3ResponseError:
        print 'Could not upload static resources. Error: %s' % (str(sys.exc_info()))
        raise


def getFilePaths(directory):
    for dirpath, _, filenames in os.walk(directory):
        for f in filenames:
            yield os.path.join(dirpath, f)


def get_env_creds():
    ''' gets creds from env vars '''
    try:
        access_key = os.environ['AWS_ACCESS_KEY_ID']
        secret_key = os.environ['AWS_SECRET_KEY']
        return access_key, secret_key
    except:
        raise Exception('Could not get creds from envvars: %s'
                        % str(sys.exc_info()))


# deprecated; cant use temp creds otherwise signatures are temp
def get_temp_creds():
    ''' returns current set of temp iam role creds '''
    metadata_url = 'http://169.254.169.254/latest/meta-data/iam/security-credentials/'
    iam_role_name = urllib2.urlopen(metadata_url).read()
    json_response = json.loads(urllib2.urlopen(metadata_url +
                                               iam_role_name).read())
    access_key = json_response['AccessKeyId']
    secret_key = json_response['SecretAccessKey']
    token = json_response['Token']
    return access_key.encode('ascii'), secret_key.encode('ascii'), token.encode('ascii')


def get_user(request):
    ''' return the auth_user who performed the request,
        or none if not found '''
    try:
        auth_user = request.cookies.get('auth_user')
        if auth_user == '':
            return 'unknown'
        else:
            return auth_user
    except:
        return 'error'


def get_s3_files(prefix):
    ''' lists files froms s3 instead of local disk
        returns tuple of (name, verion_id, last modified, size in K)
    '''
    bucket_name = os.environ['BUCKET']

    try:
        ak, sk = get_env_creds()
        s3 = boto.connect_s3(aws_access_key_id=ak,
                             aws_secret_access_key=sk)
        bucket = s3.get_bucket(bucket_name)
    except:
        logging.error('get_s3_files: Could not connect to AWS/Bucket: %s'
                      % str(sys.exc_info()))
    files = bucket.list_versions(prefix=prefix)
    filelist = []
    for f in files:
        if type(f) is not boto.s3.key.Key:
            continue
        size_in_mb = '%.2f' % (float(f.size) / (1024*1024))  # as a string
        dfmt = '%Y-%m-%dT%H:%M:%S.000Z'
        date = datetime.strptime(f.last_modified, dfmt)
        filelist.append((f.name, f.version_id, date, size_in_mb))
    return filelist


def get_s3_files_table(prefix):
    ''' list files from s3, to be used with table listing; return dicts '''
    bucket_name = os.environ['BUCKET']

    try:
        ak, sk = get_env_creds()
        s3 = boto.connect_s3(aws_access_key_id=ak,
                             aws_secret_access_key=sk)
        bucket = s3.get_bucket(bucket_name)
    except:
        logging.error('get_s3_files: Could not connect to AWS/Bucket: %s'
                      % str(sys.exc_info()))
    files = bucket.list_versions(prefix=prefix)
    filelist = []
    for f in files:
        if type(f) is not boto.s3.key.Key:
            continue
        size_in_mb = '%.2f' % (float(f.size) / (1024*1024))
        key = f.name[len(prefix):]
        directory = key.partition('/')[0]
        filename = key.partition('/')[-1]
        cb64 = urllib2.quote((f.name).encode('base64').rstrip())
        vb64 = urllib2.quote(f.version_id.encode('base64').rstrip())
        dfmt = '%Y-%m-%dT%H:%M:%S.000Z'
        date = datetime.strptime(f.last_modified, dfmt)
        d = { 'name' : filename,
              'dir'  : directory,
              'v_id' : f.version_id,
              'date' : date,
              'size' : size_in_mb,
              'cb64' : cb64,
              'vb64' : vb64,
              'key'  : key}
        filelist.append(d)
    return filelist


def ztree_files(prefix):
    ''' Takes in a list of s3 keys and generates a JSON doc
        to be used by ztree, for pretty print listing '''
    s3files = get_s3_files(prefix)
    filesd = {}
    # generate the dictionary
    for f in s3files:
        key = f[0][len(prefix):]  # ignore this universal prefix
        version_id = f[1]
        last_modified = f[2]
        size = f[3]
        directory = key.partition('/')[0]
        filename = key.partition('/')[-1]
        filetuple = (filename, version_id, last_modified, size)
        if directory not in filesd:
            filesd[directory] = []
            filesd[directory].append(filetuple)
            continue
        if directory in filesd:
            filesd[directory].append(filetuple)

    outd = []
    # create a dict of array of children nodes
    for key in filesd.keys():
        childdict = []
        for child in filesd[key]:
            name = child[0]
            version_id = child[1]
            last_modified = child[2]
            size = child[3]
            filestring = '[%s] %s - %s MiB' % (last_modified, name, size)  # the displayed text
            cb64 = urllib2.quote((prefix + key + '/' + name).encode('base64').rstrip())  # used for download link only
            vb64 = urllib2.quote(version_id.encode('base64').rstrip())
            childdict.append({'name': filestring,
                              'url': '/gendl?keyname=' + cb64 + '&version=' + vb64})
        outd.append({'name': key,
                     'children': childdict,
                     'url': '/files?folder=' + key + '&view=tree'})

    return json.dumps(outd)


def get_temp_s3_url(keyname, version_id):
    ''' generates a temporary download url for keyname; limited lifetime '''
    bucket_name = os.environ['BUCKET']

    try:
        ak, sk = get_env_creds()
        s3 = boto.connect_s3(aws_access_key_id=ak,
                             aws_secret_access_key=sk)
        bucket = s3.get_bucket(bucket_name)
    except:
        logging.error('temp_s3_url: Could not connect to AWS/Bucket: %s'
                      % str(sys.exc_info()))
    try:
        key = bucket.get_key(key_name=keyname, version_id=version_id)
        return key.generate_url(expires_in=3600)
    except:
        logging.error('Could not generate temp url: %s'
                      % str(sys.exc_info()))
        return 'Error'


def valid_name(s):
    ''' returns True if name 's' is a valid bucket name '''
    whitelist = string.ascii_letters + '0123456789-_'
    for c in s:
        if c not in whitelist:
            return False
    return True


def gen_policy(bucket_name,
               directory,
               expiration,
               max_byte_size=10737418240):

    ''' Generates a Policy based on given params. Returns a string
        expiration date must be in ISO8601 format '''

    policy = '''{{"expiration": "{0}",
                  "conditions": [
                                   {{ "bucket" : "{1}" }},
                                   [ "starts-with", "$key", "{2}/"],
                                   {{ "acl" : "private"}},
                                   {{ "x-amz-server-side-encryption" : "AES256" }},
                                   [ "content-length-range", 0, {3} ]
                                 ]
                  }}'''.format(expiration,
                               bucket_name,
                               directory,
                               int(max_byte_size))
    return policy


def sign_policy(policy, secret):
    ''' signs policy with secret, returns signature and b64 policy
    this method will b64 encode both; '''
    policy = base64.b64encode(str(policy))
    signature = base64.b64encode(hmac.new(secret, policy, hashlib.sha1).digest())
    return signature, policy


def upload_s3(contents,
              bucket_name):
    ''' Upload a file to the s3 bucket, set permissions to everyone read
        return url '''

    try:
        ak, sk = get_env_creds()
        s3 = boto.connect_s3(aws_access_key_id=ak,
                             aws_secret_access_key=sk)
        bucket = s3.get_bucket(bucket_name)
    except:
        print 'Could not connect to AWS/Bucket: %s' % str(sys.exc_info())

    try:
        k = boto.s3.key.Key(bucket)
        filename = str(uuid.uuid4()) + '.html'
        k.key = 'upload_forms/' + filename
        k.content_type = 'html'
        k.set_contents_from_string(contents)
        k.make_public()
        return k.generate_url(expires_in=60 * 60 * 24 * 30)
    except:
        print 'Error uploading html form to s3'


def create_folder_and_lifecycle(bucket_name, directory, expiration):
    ''' creates or modifies an existing folder and modifies
        the expiration lifecyce '''
    # Connect to s3 and get the bucket object
    try:
        ak, sk = get_env_creds()
        s3 = boto.connect_s3(aws_access_key_id=ak,
                             aws_secret_access_key=sk)
        bucket = s3.get_bucket(bucket_name)
    except:
        print 'Could not connect to AWS/Bucket: %s' % str(sys.exc_info())
    # if there are no files in this folder yet, create a placeholder lifecycle file
    try:
        count = 0
        files = bucket.list(prefix=directory)
        for f in files:
            count += 1
        if count <= 1:  # insert a dummy file; needed elsewise the policy won't apply
            k = boto.s3.key.Key(bucket)
            k.key = directory + '/.lifecycle_policy.txt'
            utc_now = datetime.utcnow()
            exp_time = utc_now + timedelta(days=expiration)
            content = ('This file was created by the upload portal. The '
                       'expiration policy for this folder was created on %s.'
                       ' These file(s) will automatically expire %s days'
                       ' later, on %s.') % (utc_now.ctime(),
                                            str(expiration),
                                            exp_time.ctime())
            k.set_contents_from_string(content)
    except:
        pass
    # Create and apply the life cycle object to the prefix
    try:
        directory = directory.encode('ascii')
        lifecycle = Lifecycle()
        lifecycle.add_rule(id=directory,
                           prefix=directory,
                           status='Enabled',
                           expiration=expiration)
        bucket.configure_lifecycle(lifecycle)
    except:
        return 'Error creating lifecycle: %s' % str(sys.exc_info())

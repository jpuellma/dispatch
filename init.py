#!/usr/bin/python
import boto3
import os
import sys

iam = boto3.client('iam')
s3 = boto3.client('s3')

managedPolicies = ['AmazonEC2FullAccess', 'AmazonRoute53FullAccess', 'AmazonS3FullAccess', 'IAMFullAccess', 'AmazonVPCFullAccess']
arn_prefix = 'arn:aws:iam::aws:policy/'

def getUsers(session):
    iam = session.client('iam')
    
    users = []
    paginator = iam.get_paginator('list_users')
    for response in paginator.paginate():
        for user_name in response['Users']:
            users.append(user_name['UserName'])
    return users

def getGroups(session):
    iam = session.client('iam')

    groups = []
    paginator = iam.get_paginator('list_groups')
    for response in paginator.paginate():
        for group_name in response['Groups']:
            groups.append(group_name['GroupName'])
    return groups

def getUserGroups(session, user):
    iam = session.client('iam')

    userGroups = []
    response = iam.list_groups_for_user(UserName=user)
    for group in response['Groups']:
        userGroups.append(group['GroupName'])
    return userGroups

def getAttachedPolicies(session, group):
    iam = session.client('iam')

    policies = []
    response = iam.list_attached_group_policies(GroupName=group)
    for policy in response['AttachedPolicies']:
        policies.append(policy['PolicyName'])
    return policies

def getS3buckets(session):
    s3 = session.client('s3')

    nameList = []
    buckets = s3.list_buckets()
    for bucket in buckets['Buckets']:
        nameList.append(bucket['Name'])
    return nameList

def assignPolicies(session, group):
    iam = session.client('iam')
    flag = False
    policies = getAttachedPolicies(session, group)
    for policy in managedPolicies:
        if policy not in policies:
            flag = True
            break
    if flag:
        for policy in managedPolicies:
            arn = arn_prefix + policy
            iam.attach_group_policy(GroupName=group, PolicyArn=arn) 


def setCreds(access_key_id, secret_access_key):
    session = boto3.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )
    return session
    

def exerciseCreds(session):
    print '\n    Testing provided credentials...'
    iam = session.client('iam')
    s3 = session.client('s3')
    try:
        iam.list_users()
        iam.list_groups()
        s3.list_buckets()
        print '    ...credentials successfully authenticated.\n'
    except Exception as e:
        print e
        return sys.exit()

def kopsDeps(session, name, org):
    print '\n KOPS dependency checks:'
    iam = session.client('iam')
    s3 = session.client('s3')

    iamGroup = 'kops-k8s-deployments'
    iamUser = 'kops-admin-'+name
    kopsBucket = org+'-dispatch-kops-state-store'

    userDetails = {}
    userDetails['bucket'] = kopsBucket

    #Create KOPS S3 bucket
    buckets = getS3buckets(session)
    if kopsBucket in buckets:
        print(' . Using s3://%s for KOPS state.') % kopsBucket
    else:
        print ' + Creating KOPS state S3 bucket: %s' % kopsBucket
        s3.create_bucket(ACL='private', Bucket=kopsBucket, )
        s3.put_bucket_encryption(
            Bucket=kopsBucket,
            ServerSideEncryptionConfiguration={
                'Rules': [
                    {
                        'ApplyServerSideEncryptionByDefault': {
                            'SSEAlgorithm': 'AES256',
                        }
                    },
                ]
            }
        )
        s3.put_bucket_versioning(
                         Bucket=kopsBucket,
                         VersioningConfiguration={'Status': 'Enabled'}
        )

    #Create kops IAM group
    groups = getGroups(session)
    if iamGroup in groups:
        print' . IAM group %s exists.' % iamGroup
    else:
        print ' + Creating IAM group: %s' % iamGroup
        iam.create_group(GroupName=iamGroup)
    
    #Attach managed AWS policies to group
    assignPolicies(session, iamGroup)

    #Create kops IAM user
    users = getUsers(session)
    if iamUser in users:
        print' . IAM user %s exists.' % iamUser
        userDetails['AccessKeyId'] = None
        userDetails['SecretAccessKey'] = None
    else:
        print ' + Creating KOPS admin user: %s' % iamUser 
        iam.create_user(UserName=iamUser)
        response = iam.create_access_key(UserName=iamUser)
        userDetails['AccessKeyId'] = response['AccessKey']['AccessKeyId']
        userDetails['SecretAccessKey'] = response['AccessKey']['SecretAccessKey']
        print' + %s Access Key ID: %s' % (iamUser, response['AccessKey']['AccessKeyId'])
        print' + %s Secret Access Key: %s' % (iamUser, response['AccessKey']['SecretAccessKey'])
        print'   *** Record the user Secret Access Key, it cannot be retrieved again! ***'
    
    #Add kops IAM user to KOPS deployment group
    userGroups = getUserGroups(session, iamUser)
    if iamGroup in userGroups:
        print ' . %s user is in group %s\n' % (iamUser, iamGroup)
    else:
        print ' + Adding %s user to KOPS deployment group %s\n' % (iamUser, iamGroup)
        iam.add_user_to_group(GroupName=iamGroup, UserName=iamUser)
    
    return userDetails
#!/usr/bin/env python3
'''
Builds and serves the documention sites of every branch
'''

import logging
import threading
import os
import json
import sys

from shutil import copytree, rmtree
from random import randint
from flask import Flask, Response, request

import git
# defaults

DEFAULT_STATE_FILE='/tmp/build_state.json'
DEFAULT_WORK_PATH = "work"
DEFAULT_BUILD_ROOT = "/tmp/preview-bot/builds"
DEFAULT_REMOTE_URL = "https://github.com/CSCfi/csc-user-guide"
DEFAULT_SITE_URL = "https://csc-guide-preview.rahtiapp.fi/"
DEFAULT_SECRET = "changeme" # we are using secret but we should be utilizing whitelists
DEFAULT_PORT = 8081

try:
    STATEFILE = os.environ["STATEFILE"]
except KeyError:
    STATEFILE = '/tmp/build_state.json'

try:
    WORK_PATH = os.environ["WORKPATH"]
except KeyError:
    WORK_PATH = DEFAULT_WORK_PATH

try:
    BUILD_ROOT = os.environ["BUILDROOT"]
except KeyError:
    BUILD_ROOT = DEFAULT_BUILD_ROOT

try:
    SITE_URL = os.environ["SITEURL"]
except KeyError:
    SITE_URL = DEFAULT_SITE_URL

try:
    BUILD_SECRET = os.environ["BUILDSECRET"]
except KeyError:
    BUILD_SECRET = DEFAULT_SECRET

try:
    PORT = os.environ["PORT"]
except KeyError:
    PORT = DEFAULT_PORT

try:
    REMOTE_URL = os.environ["REMOTEURL"]
except KeyError:
    REMOTE_URL = "https://github.com/CSCfi/csc-user-guide"

# Configurations in CONFIGFILE will override other environment variables
try:
    CONFIG_FILE = os.environ["CONFIGFILE"]
except KeyError:
    CONFIG_FILE = None

# Default configuration

config = {
    "workPath": WORK_PATH,
    "remoteUrl": REMOTE_URL,
    "buildRoot": BUILD_ROOT,
    "debug": "True",
    "secret": BUILD_SECRET,
    "prune": "True"
    }

#build_state = {}

### non-route functions

def init_repo(init_path, remote_url):
    """
    Updates current repository to match `origin` remote.
    Does pruning fetch.
    """

    mkdirp(init_path)

    repo = git.Repo.init(init_path)

    try:
        origin = repo.remote('origin')
    except ValueError:
        app.logger.info(f"Creating origin {remote_url} into {init_path}")
        origin = repo.create_remote('origin', remote_url)

    assert origin.exists()
    assert origin == repo.remotes.origin == repo.remotes['origin']

    app.logger.info("* Fetching remote branches' content")
    for fetch_info in origin.fetch(None, None, prune=True):
        app.logger.info("  Branch [%s], commit [%s]" % (fetch_info.ref, fetch_info.commit))

    return repo, origin

def mkdirp(path):
    os.makedirs(path, exist_ok=True)

def buildRef(repo, ref, state):
    """
    Builds and updates.
    """
    global config

    buildpath = os.path.join(config["buildRoot"], str(ref))

    app.logger.info('Checking [%s]: %s == %s' % (ref, str(ref.commit), state["built"]))

    if not str(ref.commit) == state["built"] or not os.path.isdir(buildpath):
        app.logger.info("  [%s] re-building %s" % (ref, ref.commit))
        repo.git.reset('--hard',ref)
        repo.git.checkout(ref)
        app.logger.debug("  [%s] buildpath = %s" % (ref, buildpath))
        mkdirp(buildpath)

        scripts=["generate_alpha.sh","generate_by_system.sh","generate_new.sh","generate_glossary.sh"]

        for script in scripts:
            cmd = "sh -c 'cd %s && ./scripts/%s 2>&1'" % (config["workPath"],script)
            cmdout = os.popen(cmd)
            line = cmdout.readline()
            app.logger.info(f"  [{ref}] # {cmd}")
            if cmdout.close():
                app.logger.error(f"  [{ref}] {line}")
            else:
                app.logger.info(f"  [{ref}] {line}")

        #
        # WORKAROUND
        with open(f"{config['workPath']}/mkdocs.yml", 'r', encoding="utf-8") as file :
            filedata = file.read()

        # Replace the target string
        filedata = filedata.replace(f'SITE_URL: "{SITE_URL}"', f'SITE_URL: "{SITE_URL}{str(ref)}"')

        # Write the file out again
        with open(f"{config['workPath']}/mkdocs.yml2", 'w', encoding="utf-8") as file:
            file.write(filedata)
        #

        cmd = "sh -c 'cd %s && mkdocs build --site-dir %s -f mkdocs.yml2 2>&1'" % (config["workPath"], buildpath)
        app.logger.info(f"  [{ref}] # %s" % (cmd))
        cmdout = os.popen(cmd)
        app.logger.debug(cmdout.read())

        state["built"] = str(ref.commit)

def buildCommit(commit, branch):

    buildpath = os.path.join(config["buildRoot"], branch)

    tmpFolder = '/tmp/%s-%s' % (commit, randint(0,9999))

    try:
        rmtree(tmpFolder)
    except Exception:
        pass

    copytree(config["workPath"], tmpFolder)

    repo = git.Repo.init(tmpFolder)

    repo.git.reset('--hard', commit)
    repo.git.checkout(commit)

    mkdirp(buildpath)

    scripts=["generate_alpha.sh","generate_by_system.sh","generate_new.sh","generate_glossary.sh"]

    for script in scripts:
        cmd = "sh -c 'cd %s && ./scripts/%s 2>&1'" % (tmpFolder, script)
        print("Executing: %s" % (cmd))
        cmdout = os.popen(cmd)
        print(cmdout.read())

    #
    # WORKAROUND
    with open(f"{tmp_folder}/mkdocs.yml", 'r', encoding="utf-8") as file :
        filedata = file.read()

    # Replace the target string
    filedata = filedata.replace(f"SITE_URL: {SITE_URL}", f'SITE_URL: "{SITE_URL}{branch}"')

    # Write the file out again
    with open(f'{tmp_folder}/mkdocs.yml2', 'w', encoding="utf-8") as file:
        file.write(filedata)
        #

    cmd = "sh -c 'cd %s && mkdocs build --site-dir %s -f mkdocs.yml2 2>&1'" % (tmpFolder, buildpath)
    print("Executing: %s" % (cmd))
    cmdout = os.popen(cmd)
    print(cmdout.read())

    app.logger.info("Built branch {branch} in commit {commit}")

    #buildState = read_state()

    try:
        buildState[str(branch)]["built"] = str(commit)
    except KeyError:
        buildState[str(branch)] = {"sha": str(commit), "status": "init", "built": str(commit)}
        #write_state(buildState)

    #write_state(buildState)

    rmtree(tmpFolder)

def cleanUpZombies():
    """
    We want to clean all Zombies:
    * When spid is 0, child processes exist, but they are still alive
    * When ChildProcessError raises, it means that there are no children left
    """

    app.logger.info("* Cleaning up Zombies")
    spid = -1
    while spid != 0:
        try:
            spid, status, rusage = os.wait3(os.WNOHANG)
            app.logger.debug("* Process %d with status %d" % (spid, status))
        except ChildProcessError:
            break

def pruneBuilds(repo, origin):
    try:
        builtrefs = os.listdir(config["buildRoot"]+'/origin')
    except FileNotFoundError:
        app.logger.debug("* Clean buildRoot")
        return

    srefs = [str(x) for x in origin.refs]
    builtrefs = ['origin/'+str(x) for x in builtrefs]

    app.logger.debug("* Pruning old builds.")

    for bref in builtrefs:
        if not bref in srefs:
            print('found stale preview: ' + bref)
            remove_build = config["buildRoot"] + '/' + bref
            print('Removing ' + remove_build)
            rmtree(remove_build)

    app.logger.debug("DONE pruning old builds.")

def get_branch(commit):
    '''
    Given a commit, it returns the corresponding branch containing the commit
    '''
    repo, _ = init_repo(config["workPath"], config["remoteUrl"])

    # Get the branch name
    for ref in repo.refs:
        if str(ref.commit.hexsha) == str(commit):
            return ref.name

    return None

### Route functions ###

app = Flask(__name__)

@app.route("/build/<string:secret>", methods=["GET", "POST"])
def listenBuild(secret):
    global buildState
    global config

    if not secret == config["secret"]:
        return "Access denied"

    if request.headers.get('Content-Type') == 'application/json':

        commit = request.json['after']
        branch = get_branch(commit)
        if branch is None:
            commit = request.json['after']
            branch = get_branch(commit)

        if branch == None:
            return Response(f"Branch not found for commit {commit}")

        print(branch)

        thread = threading.Thread(target=buildCommit, args=[commit, branch])
        thread.start()

        return Response(f"{{\"commit\":\"{commit}\",\"branch\":\"{branch}\"}}" )

    thread = threading.Thread(target=build)
    thread.start()

    return Response('{\"built\":\"started\"}')


def build():

    app.logger.info("* Start build loop")

    buildState = read_state()

    repo, origin = init_repo(config["workPath"], config["remoteUrl"])

    output = ""

    # Clean buildState
    for ref in origin.refs:
        sref = str(ref)
        output = output + "Found %s (%s)<br>" % (sref, str(ref.commit))

        if not sref in buildState:
            app.logger.debug(f"Adding {sref} branch to build state")
            buildState[sref] = {"sha": str(ref.commit), "status": "init", "built": None}

    # Prune nonexisting builds
    if "prune" in config and config["prune"]:
        pruneBuilds(repo, origin)
    # Refresh builds
    for ref in origin.refs:
        buildRef(repo, ref, buildState[str(ref)])
        write_state(buildState)

    cleanUpZombies()

def write_state(state):
    '''
    Writes the state of the brnaches and their commits into the JSON state file
    '''
    with open(STATEFILE, 'w', encoding="utf-8") as file:
        json.dump(state, file)

def read_state():
    try:
        with open(STATEFILE, 'r', encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
### Entry functions

if __name__=="__main__":
    app.logger.setLevel(logging.INFO)

    if CONFIG_FILE is not None:
        app.logger.info("Loading configuration from file: " + CONFIG_FILE)
        with open(CONFIG_FILE, encoding="utf-8") as config_file:
            config = json.load(config_file)
        BUILD_SECRET = config["secret"]
        WORK_PATH = config["workPath"]
        BUILD_ROOT = config["buildRoot"]

    app.logger.info("WORK_PATH: " + WORK_PATH)
    app.logger.info("BUILD_ROOT: " + BUILD_ROOT)
    app.logger.info("BUILD_SECRET: " + BUILD_SECRET)

    if BUILD_SECRET == DEFAULT_SECRET:
        app.logger.error("Don't use default secret since it's freely available in the internet")
        exit(1)

    thread = threading.Thread(target=build)
    thread.start()

    app.run(debug=config["debug"]=="True",
        port=PORT,
        host='0.0.0.0')

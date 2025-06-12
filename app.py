#!/usr/bin/env python3
'''
Builds and serves the documention sites of every branch
'''

import logging
import threading
import os
import json
import sys
import signal
from urllib.parse import urljoin

from shutil import copytree, rmtree
from random import randint
from flask import Flask, Response, request

import git
from git.exc import GitCommandError
# defaults

DEFAULT_STATE_FILE='/tmp/build_state.json'
DEFAULT_WORK_PATH = "work"
DEFAULT_BUILD_ROOT = "/tmp/preview-bot/builds"
DEFAULT_BASE_CONFIG = "mkdocs.yml"
DEFAULT_REMOTE_URL = "https://github.com/CSCfi/csc-user-guide"
DEFAULT_SITE_URL = "https://csc-guide-preview.2.rahtiapp.fi/"
DEFAULT_SECRET = "changeme" # we are using secret but we should be utilizing whitelists
DEFAULT_PORT = 8081
DEFAULT_SHELL_SCRIPTS_DIR = "scripts"
DEFAULT_SHELL_SCRIPTS = ("generate_alpha.sh",
                         "generate_by_system.sh",
                         "generate_new.sh",
                         "generate_glossary.sh")

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
    BASE_CONFIG = os.environ["BASECONFIG"]
except KeyError:
    BASE_CONFIG = DEFAULT_BASE_CONFIG

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

try:
    SHELL_SCRIPTS_DIR = os.environ["SHELL_SCRIPTS_DIR"]
except KeyError:
    SHELL_SCRIPTS_DIR = DEFAULT_SHELL_SCRIPTS_DIR

try:
    SHELL_SCRIPTS = os.environ["SHELL_SCRIPTS"].split(" ")
except KeyError:
    SHELL_SCRIPTS = DEFAULT_SHELL_SCRIPTS

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
    "prune": "True",
    "shellScriptsDir": SHELL_SCRIPTS_DIR,
    "shellScripts": SHELL_SCRIPTS
    }

#build_state = {}

### non-route functions
def get_scripts(basepath):
    class ShellScript:
        @staticmethod
        def _prepend_scripts_dir(fname):
            return os.path.join(config["shellScriptsDir"], fname)

        @staticmethod
        def _script_exists(fpath, context_dir):
            script_fpath = os.path.join(context_dir, fpath)
            return os.path.isfile(script_fpath)

        def __new__(cls, fname, context_dir):
            fpath = cls._prepend_scripts_dir(fname)

            return (cls(fpath, context_dir)
                    if cls._script_exists(fpath, context_dir)
                    else None)

        def __init__(self, fpath, context_dir):
            self.__fpath = fpath
            self.__dir = context_dir

        @property
        def cmd(self):
            return f"sh -c 'cd {self.__dir} && ./{self.__fpath} 2>&1'"

    scripts = [ShellScript(fname, basepath) for fname in config["shellScripts"]]
    existent = filter(lambda s: s is not None, scripts)

    return list(existent)


def get_build_cmd(work_dir, build_dir, subpath, base_url=SITE_URL, base_config=BASE_CONFIG):
    """Returns a shell command for building a preview of a branch in work_dir into build_dir with subpath appended to site_url.
    """
    mkdocs_config = f"{{INHERIT: {base_config}, site_url: {urljoin(base_url, subpath)}, site_dir: {build_dir}}}"
    mkdocs_cmd = f"echo \"'\"{mkdocs_config}\"'\" | mkdocs build --config-file -"

    return f"sh -c 'cd {work_dir} && {mkdocs_cmd} 2>&1'"

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
        app.logger.info(f"  Branch [{fetch_info.ref}], commit [{fetch_info.commit}]")

    return repo, origin

def mkdirp(path):
    '''
    Makes the dir and it does not complain if it exists
    '''
    os.makedirs(path, exist_ok=True)

def build_ref(repo, ref, state):
    """
    Builds and updates.
    """
    #global config

    buildpath = os.path.join(config["buildRoot"], str(ref))

    app.logger.info(f"Checking [{ref}]: {str(ref.commit)} == {state['built']}")

    if os.path.isdir(buildpath) and str(ref.commit) == state["built"]:
        app.logger.info(f"         [{str(ref)}]: is up to date")
        return

    app.logger.info(f"  [{ref}] re-building {ref.commit}")
    try:
        repo.git.reset('--hard',ref)
    except GitCommandError:
        app.logger.error(f"         [{str(ref)}]: cannot reset hard at this moment")

    repo.git.checkout(ref)
    app.logger.debug(f"  [{ref}] buildpath = {buildpath}")
    mkdirp(buildpath)

    for script_obj in get_scripts(config['workPath']):
        cmd = script_obj.cmd
        cmdout = os.popen(cmd)
        line = cmdout.readline()
        app.logger.info(f"  [{ref}] # {cmd}")
        if cmdout.close():
            app.logger.error(f"  [{ref}] {line}")
        else:
            app.logger.info(f"  [{ref}] {line}")

    cmd = get_build_cmd(config['workPath'],
                        buildpath,
                        str(ref))

    app.logger.info(f"  [{ref}] # %s" % (cmd))
    cmdout = os.popen(cmd)
    app.logger.debug(cmdout.read())

    cmdout.close()

    state["built"] = str(ref.commit)

def build_commit(commit, branch):
    '''
    Builds the given commit into the given branch folder. Uses a random tmp fold for the git.
    '''

    buildpath = os.path.join(config["buildRoot"], branch)

    tmp_folder = f'/tmp/{commit}-{randint(0,9999)}'

    try:
        rmtree(tmp_folder)
    except OSError:
        pass

    copytree(config["workPath"], tmp_folder)

    repo = git.Repo.init(tmp_folder)

    repo.git.reset('--hard', commit)
    repo.git.checkout(commit)

    mkdirp(buildpath)

    for script_obj in get_scripts(tmp_folder):
        cmd = script_obj.cmd
        print(f"Executing: {cmd}")
        cmdout = os.popen(cmd)
        print(cmdout.read())

        cmdout.close()

    cmd = get_build_cmd(tmp_folder,
                        buildpath,
                        branch)

    print(f"Executing: {cmd}")
    cmdout = os.popen(cmd)
    print(cmdout.read())
    cmdout.close()

    app.logger.info("Built branch {branch} in commit {commit}")

    build_state = read_state()

    try:
        build_state[str(branch)]["built"] = str(commit)
    except KeyError:
        build_state[str(branch)] = {"sha": str(commit), "status": "init", "built": str(commit)}
        write_state(build_state)

    write_state(build_state)

    rmtree(tmp_folder)

def clean_up_zombies():
    """
    We want to clean all Zombies:
    * When spid is 0, child processes exist, but they are still alive
    * When ChildProcessError raises, it means that there are no children left
    """

    app.logger.info(f"* Cleaning up Zombies. This is {os.getpid()}" )
    spid = -1
    while spid != 0:
        try:
            spid, status, _ = os.wait3(os.WNOHANG)
            app.logger.info(f"* Process {spid} with status {status}")
        except ChildProcessError:
            break
    app.logger.info("Cleaning process done.")

def prune_builds(origin):
    '''
    Deletes any branch folder that is no longer in the repository
    '''
    try:
        builtrefs = os.listdir(config["buildRoot"]+'/origin')
    except FileNotFoundError:
        app.logger.debug("* Clean BUILD_ROOT")
        return

    srefs = [str(x) for x in origin.refs]
    builtrefs = ['origin/'+str(x) for x in builtrefs]

    app.logger.debug("* Pruning old builds.")

    for bref in builtrefs:
        if not bref in srefs:
            print(f'found stale preview: {bref}')
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
def listen_build(secret):
    '''
    This method listens to the given URL:
      - Check the secret matchs
      - If GET, checks all brnaches and builds the ones missing
      - If POST, reads the json and builds the update branch
    '''
    #global config

    if not secret == config["secret"]:
        return "Access denied"

    if request.headers.get('Content-Type') == 'application/json':

        commit = request.json['after']
        branch = get_branch(commit)
        if branch is None:
            commit = request.json['after']
            branch = get_branch(commit)

        if branch is None:
            return Response(f"Branch not found for commit {commit}")

        print(branch)

        build_commit_thread = threading.Thread(target=build_commit, args=[commit, branch])
        build_commit_thread.start()

        return Response(f"{{\"commit\":\"{commit}\",\"branch\":\"{branch}\"}}" )

    build_thread = threading.Thread(target=build)
    build_thread.start()

    return Response('{\"built\":\"started\"}',
                    content_type="application/json")


def build():
    '''
    Clones the repo, and makes sure that every branch is built, and prunes the deleted branches
    '''
    app.logger.info("* Start build loop")

    build_state = read_state()

    repo, origin = init_repo(config["workPath"], config["remoteUrl"])

    output = ""

    # Clean build_state
    for ref in origin.refs:
        sref = str(ref)
        output = output + f"Found {sref} ({str(ref.commit)})<br>"

        if not sref in build_state:
            app.logger.debug(f"Adding {sref} branch to build state")
            build_state[sref] = {"sha": str(ref.commit), "status": "init", "built": None}

    # Prune nonexisting builds
    if "prune" in config and config["prune"]:
        prune_builds(origin)
    # Refresh builds
    for ref in origin.refs:
        build_ref(repo, ref, build_state[str(ref)])
        write_state(build_state)

def write_state(state):
    '''
    Writes the state of the brnaches and their commits into the JSON state file
    '''
    with open(STATEFILE, 'w', encoding="utf-8") as file:
        json.dump(state, file)

def read_state():
    '''
    Read the current state of bes and commits from file
    '''
    try:
        with open(STATEFILE, 'r', encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}

def signal_handler(sig, frame):
    clean_up_zombies()

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
        sys.exit(1)

    thread = threading.Thread(target=build)
    thread.start()

    signal.signal(signal.SIGCHLD, signal_handler)

    app.run(debug=config["debug"]=="True",
        port=PORT,
        host='0.0.0.0')

#!/usr/bin/env python3
import git, os, shutil, json, threading

import logging

from flask import Flask, Response

# defaults

defaultStateFile='/tmp/build_state.json'
defaultWorkPath = "work"
defaultBuildRoot = "/tmp/preview-bot/builds"
defaultRemoteUrl = "https://github.com/CSCfi/csc-user-guide"
defaultSiteURL = "https://csc-guide-preview.rahtiapp.fi/"
defaultSecret = "changeme" # we are using secret but we should be utilizing whitelists
defaultPort = 8081

try:
    STATEFILE = os.environ["STATEFILE"]
except KeyError:
    STATEFILE = '/tmp/build_state.json'

try:
  workPath = os.environ["WORKPATH"]
except KeyError:
  workPath = defaultWorkPath

try:
  buildRoot = os.environ["BUILDROOT"]
except KeyError:
  buildRoot = defaultBuildRoot

try:
  siteURL = os.environ["SITEURL"]
except KeyError:
  siteURL = defaultSiteURL

try:
  buildSecret = os.environ["BUILDSECRET"]
except KeyError:
  buildSecret = defaultSecret

try:
  remoteUrl = os.environ["REMOTEURL"]
except KeyError:
  remoteUrl = "https://github.com/CSCfi/csc-user-guide"

# Configurations in CONFIGFILE will override other environment variables
try:
  configFile = os.environ["CONFIGFILE"]
except KeyError:
  configFile = None

# Default configuration 

config = {
    "workPath": workPath, 
    "remoteUrl": remoteUrl,
    "buildRoot": buildRoot,
    "debug": "True",
    "secret": buildSecret,
    "prune": "True"
    }

buildState = {}

### non-route functions

def initRepo(workPath, remote_url):
  """
  Updates current repository to match `origin` remote.
  Does pruning fetch.
  """

  mkdirp(workPath)

  repo = git.Repo.init(workPath)

  try:
    origin = repo.remote('origin')
  except ValueError:
    app.logger.info(f"Creating origin {remote_url} into {workPath}")
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
    with open('%s/mkdocs.yml' % config["workPath"], 'r') as file :
      filedata = file.read()

    # Replace the target string
    filedata = filedata.replace('site_url: "%s"' % siteURL, 'site_url: "%s%s"' % (siteURL, str(ref)))

    # Write the file out again
    with open('%s/mkdocs.yml2' % config["workPath"], 'w') as file:
      file.write(filedata)
    #

    cmd = "sh -c 'cd %s && mkdocs build --site-dir %s -f mkdocs.yml2 2>&1'" % (config["workPath"], buildpath)
    app.logger.info(f"  [{ref}] # %s" % (cmd))
    cmdout = os.popen(cmd)
    app.logger.debug(cmdout.read())

    state["built"] = str(ref.commit)

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
      remove_build = config["buildRoot"] + '/' + bref
      prinf(f"  [{bref}] Removing {remove_build}")
      shutil.rmtree(remove_build)

  app.logger.debug("DONE pruning old builds.")

### Route functions ###

app = Flask(__name__)

@app.route("/build/<string:secret>", methods=["GET", "POST"])
def listenBuild(secret):
  global buildState
  global config

  if not secret == config["secret"]:
    return "Access denied"

  response = Response("Build started")

  thread = threading.Thread(target=build)
  thread.start()

  return response

def build():

  app.logger.info("* Start build loop")

  buildState = read_state()

  repo, origin = initRepo(config["workPath"], config["remoteUrl"])

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
    with open(STATEFILE, 'w') as file:
        json.dump(state, file)

def read_state():
    try:
        with open(STATEFILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
### Entry functions

if __name__=="__main__":
  app.logger.setLevel(logging.INFO)

  if not configFile == None:
    app.logger.info("Loading configuration from file: " + configFile)
    with open(configFile) as config_file:
      config = json.load(config_file)
    buildSecret = config["secret"]
    workPath = config["workPath"]
    buildRoot = config["buildRoot"]

  app.logger.info("workPath: " + workPath)
  app.logger.info("buildRoot: " + buildRoot)
  app.logger.info("buildSecret: " + buildSecret)

  if buildSecret == defaultSecret:
    app.logger.error("Don't use default secret since it's freely available in the internet")
    exit(1)

  listenBuild(config["secret"])

  app.run(debug=config["debug"]=="True",
      port=defaultPort,
      host='0.0.0.0')


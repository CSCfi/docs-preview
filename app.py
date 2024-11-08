#!/usr/bin/env python3
import git, os, shutil, json

from flask import Flask, Response

# defaults

defaultWorkPath = "work"
defaultBuildRoot = "/tmp/preview-bot/builds"
defaultRemoteUrl = "https://github.com/CSCfi/csc-user-guide"
defaultSiteURL = "https://csc-guide-preview.rahtiapp.fi/"
defaultSecret = "changeme" # we are using secret but we should be utilizing whitelists
defaultPort = 8081

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

# Configurations in CONFIGFILE will override other environment variables
try:
  configFile = os.environ["CONFIGFILE"]
except KeyError:
  configFile = None

# Default configuration 

config = {
    "workPath": workPath, 
    "remoteUrl": "https://github.com/CSCfi/csc-user-guide",
    "buildRoot": buildRoot,
    "debug": "False", 
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
    print("creating origin")
    origin = repo.create_remote('origin', remote_url)

  assert origin.exists()
  assert origin == repo.remotes.origin == repo.remotes['origin']


  for fetch_info in origin.fetch(None, None, prune=True):
    print("Updated %s in %s" % (fetch_info.ref, fetch_info.commit))

  return repo, origin

def mkdirp(path):
  os.makedirs(path, exist_ok=True)

def buildRef(repo, ref, state):
  """
  Builds and updates.
  """
  global config

  print(str(ref.commit), state["built"])
  buildpath = os.path.join(config["buildRoot"], str(ref))

  if not str(ref.commit) == state["built"] or not os.path.isdir(buildpath):
    print("re-building %s in %s" % (ref, ref.commit))
    repo.git.reset('--hard',ref)
    repo.git.checkout(ref)
    print("buildpath = %s" % (buildpath))
    mkdirp(buildpath)

    scripts=["generate_alpha.sh","generate_by_system.sh","generate_new.sh","generate_glossary.sh"]

    for script in scripts:
        cmd = "sh -c 'cd %s && ./scripts/%s 2>&1'" % (config["workPath"],script)
        print("Executing: %s" % (cmd))
        cmdout = os.popen(cmd)
        print(cmdout.read())

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
    print("Executing: %s" % (cmd))
    cmdout = os.popen(cmd)
    print(cmdout.read())

    state["built"] = str(ref.commit)

def cleanUpZombies():
    """
    We want to clean all Zombies:
    * When spid is 0, child processes exist, but they are still alive
    * When ChildProcessError raises, it means that there are no children left
    """

    print("Cleaning up Zombies")
    spid = -1
    while spid != 0:
      try:
        spid, status, rusage = os.wait3(os.WNOHANG)
        print("Process %d with status %d" % (spid, status))
      except ChildProcessError:
        break

def pruneBuilds(repo, origin):
  repo, origin = initRepo(config["workPath"], config["remoteUrl"])
  try:
    builtrefs = os.listdir(config["buildRoot"]+'/origin')
  except FileNotFoundError:
    print("Clean buildRoot")
    return

  srefs = [str(x) for x in origin.refs]
  builtrefs = ['origin/'+str(x) for x in builtrefs]

  print("Pruning old builds.")

  for bref in builtrefs:
    if not bref in srefs:
      print('found stale preview: ' + bref)
      remove_build = remove_build=config["buildRoot"] + '/' + bref
      print('Removing ' + remove_build)
      shutil.rmtree(remove_build)

  print("Done pruning old builds.")

### Route functions ###

app = Flask(__name__)

@app.route("/build/<string:secret>", methods=["GET", "POST"])
def listenBuild(secret):
  global buildState
  global config

  if not secret == config["secret"]:
    return "Access denied"

  build()

  response = Response('built started')

  response.call_on_close(build)

  return response

def build():

  print("Start build")

  repo, origin = initRepo(config["workPath"], config["remoteUrl"])

  output = ""

  # Clean buildState
  for ref in origin.refs:
    sref = str(ref)
    output = output + "Found %s (%s)<br>" % (sref, str(ref.commit))

    if not sref in buildState:
      print(sref + " not found in " + str(buildState))
      buildState[sref] = {"sha": str(ref.commit), "status": "init", "built": None}

  # Prune nonexisting builds
  if "prune" in config and config["prune"]:
    pruneBuilds(repo, origin)
  # Refresh builds
  for ref in origin.refs:
    buildRef(repo, ref, buildState[str(ref)])

  cleanUpZombies()

### Entry functions

if __name__=="__main__":
  if not configFile == None:
    print("Loading configuration from file: " + configFile)
    with open(configFile) as config_file:
      config = json.load(config_file)
    buildSecret = config["secret"]
    workPath = config["workPath"]
    buildRoot = config["buildRoot"]

  print("workPath: " + workPath)
  print("buildRoot: " + buildRoot)
  print("buildSecret: " + "******")

  if buildSecret == defaultSecret:
    print("Don't use default secret since it's freely available in the internet")
    exit(1)

  listenBuild(config["secret"])
  build()

  app.run(debug=config["debug"]=="True",
      port=defaultPort,
      host='0.0.0.0')


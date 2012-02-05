import functools
import os
import re
import subprocess
import time
import thread
import sublime
import sublime_plugin

# the AsyncProcess class has been cribbed from:
# https://github.com/maltize/sublime-text-2-ruby-tests/blob/master/run_ruby_test.py

class AsyncProcess(object):
  def __init__(self, cmd, listener):
    self.cmd = cmd
    self.listener = listener
    print "DEBUG_EXEC: " + self.cmd
    self.proc = subprocess.Popen([self.cmd], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if self.proc.stdout:
      thread.start_new_thread(self.read_stdout, ())
    if self.proc.stderr:
      thread.start_new_thread(self.read_stderr, ())

  def read_stdout(self):
    while True:
      data = os.read(self.proc.stdout.fileno(), 2**15)
      if data != "":
        sublime.set_timeout(functools.partial(self.listener.append_data, self.proc, data), 0)
      else:
        self.proc.stdout.close()
        self.listener.is_running = False
        self.listener.append_data(self.proc, "\n--- PROCESS COMPLETE ---")
        break

  def read_stderr(self):
    while True:
      data = os.read(self.proc.stderr.fileno(), 2**15)
      if data != "":
        sublime.set_timeout(functools.partial(self.listener.append_data, self.proc, data), 0)
      else:
        self.proc.stderr.close()
        self.listener.is_running = False
        break

# the StatusProcess class has been cribbed from:
# https://github.com/maltize/sublime-text-2-ruby-tests/blob/master/run_ruby_test.py

class StatusProcess(object):
  def __init__(self, msg, listener):
    self.msg = msg
    self.listener = listener
    thread.start_new_thread(self.run_thread, ())

  def run_thread(self):
    progress = ""
    while True:
      if self.listener.is_running:
        if len(progress) >= 10:
          progress = ""
        progress += "."
        sublime.set_timeout(functools.partial(self.listener.update_status, self.msg, progress), 0)
        time.sleep(1)
      else:
        break

class OutputView(object):
    def __init__(self, name, window):
        self.output_name = name
        self.window = window

    def show_output(self):
        self.ensure_output_view()
        self.window.run_command("show_panel", {"panel": "output." + self.output_name})

    def show_empty_output(self):
        self.ensure_output_view()
        self.clear_output_view()
        self.show_output()

    def ensure_output_view(self):
        if not hasattr(self, 'output_view'):
            self.output_view = self.window.get_output_panel(self.output_name)

    def clear_output_view(self):
        self.ensure_output_view()
        self.output_view.set_read_only(False)
        edit = self.output_view.begin_edit()
        self.output_view.erase(edit, sublime.Region(0, self.output_view.size()))
        self.output_view.end_edit(edit)
        self.output_view.set_read_only(True)

    def append_data(self, proc, data):
        str = data.decode("utf-8")
        str = str.replace('\r\n', '\n').replace('\r', '\n')

        selection_was_at_end = (len(self.output_view.sel()) == 1
          and self.output_view.sel()[0]
            == sublime.Region(self.output_view.size()))
        self.output_view.set_read_only(False)
        edit = self.output_view.begin_edit()
        self.output_view.insert(edit, self.output_view.size(), str)
        if selection_was_at_end:
          self.output_view.show(self.output_view.size())
        self.output_view.end_edit(edit)
        self.output_view.set_read_only(True)

class CommandBase:
    def __init__(self, window):
        self.window = window

    def show_output(self):
        if not hasattr(self, 'output_view'):
            self.output_view = OutputView('docblox', self.window)

        self.output_view.show_output()

    def show_empty_output(self):
        if not hasattr(self, 'output_view'):
            self.output_view = OutputView('docblox', self.window)

        self.output_view.clear_output_view()
        self.output_view.show_output()

    def start_async(self, caption, executable):
        self.is_running = True
        self.proc = AsyncProcess(executable, self)
        StatusProcess(caption, self)

    def append_data(self, proc, data):
        self.output_view.append_data(proc, data)

    def update_status(self, msg, progress):
        sublime.status_message(msg + " " + progress)

class DocbloxCommand(CommandBase):
    def run(self, paths):
        self.show_empty_output()

        cmd = ""
        ignore = ""

        if len(paths) > 0:

            if os.path.isfile(paths[0]):
                cmd = "cd '" + os.path.dirname(paths[0]) + "' && docblox -f " + paths[0] + " -t " + os.path.dirname(paths[0]) + "/build/api/"
                ignore = ignore + os.path.dirname(paths[0]) + "/build/api/"

            if os.path.isdir(paths[0]):
                cmd = "cd '" + paths[0] + "' && docblox -d " + paths[0] + " -t " + paths[0] + "/build/api/"
                ignore = ignore + paths[0] + "/build/api/"

        if cmd != "":
            cmd = cmd + " -i " + ignore

        self.append_data(self, "$ " + cmd + "\n")
        self.start_async("Running DocBlox", cmd)

class ActiveFile:
    def findFolderContainingFile(self, path, filename):
        if path == '/':
            return None
        if os.path.exists(path + '/' + filename):
            return [ path, filename ]

        return self.findFolderContainingFile(os.path.dirname(path), filename)

    def resetSearchedFolders(self):
        self.searchedFolders = {}

    def findFileFor(self, path, suffix, depth):
        if depth == 0:
            return None
        if path == '/':
            return None
        # optimisation - avoid looking in the same place twice
        pathToSearch = path + '/'
        filenameToTest = pathToSearch + suffix
        # print "Looking for " + filenameToTest
        if os.path.exists(filenameToTest):
            return filenameToTest
        found_path = self.searchSubfoldersFor(path, suffix)
        if found_path is not None:
            return found_path
        # avoid looking in here again
        self.searchedFolders[pathToSearch] = True
        depth = depth - 1
        return self.findFileFor(os.path.dirname(path), suffix, depth)

    def searchSubfoldersFor(self, path, suffix):
        # print "searchSubfoldersFor: " + path + ' ' + suffix
        for root, dirs, names in os.walk(path):
            for subdir in dirs:
                # print "looking at dir " + subdir
                # optimisation - avoid looking in hidden places
                if subdir[0] == '.':
                    # print "skipping hidden folder " + subdir
                    continue
                # optimisation - avoid looking down dead ends
                frontToTest = subdir + '/'
                if suffix[:len(frontToTest)] == frontToTest:
                    # print "skipping matching prefix " + frontToTest
                    continue
                # optimisation - avoid looking in the same place twice
                pathToSearch = path + '/' + subdir + '/'
                if pathToSearch in self.searchedFolders:
                    # print "Skipping " + pathToSearch
                    continue
                self.searchedFolders[pathToSearch] = True
                # if we get here, we have not discarded this folder yet
                filenameToTest = pathToSearch + suffix
                # print "Looking in subfolders for " + filenameToTest
                if os.path.exists(filenameToTest):
                    # print "Found " + filenameToTest
                    return filenameToTest
                found_path = self.searchSubfoldersFor(path + '/' + subdir, suffix)
                if found_path is not None:
                    # print "Found path!!"
                    return found_path
                # print "Run out of options"
        return None

class ActiveWindow(ActiveFile):
    def file_name(self):
        if hasattr(self, '_file_name'):
            return self._file_name

        return None

    def determine_filename(self, args=[]):
        if len(args) == 0:
            active_view = self.window.active_view()
            filename = active_view.file_name()
        else:
            filename = args[0]

        self._file_name = filename

    def is_php_buffer(self):
        ext = os.path.splitext(self.file_name())[1]
        if ext == 'php':
            return True
        return False

class DocbloxWindowBase(sublime_plugin.WindowCommand, ActiveWindow):
    def run(self, paths=[]):
        print "not implemented"

class DocbloxDocumentAllCommand(DocbloxWindowBase):
    def run(self, paths=[]):

        cmd = DocbloxCommand(self.window)
        cmd.run(paths)

    def is_enabled(self, paths=[]):
        return True

    def is_visible(self, paths=[]):
        return True

    def description(self, paths=[]):
        return 'Generate documentation...'

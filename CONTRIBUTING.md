# Contributing to Oremi Akọrin

## Before Submitting an Issue

Check that [our issue database](https://gitlab.com/demsking/oremi-akorin/issues)
doesn't already include that problem or suggestion before submitting an issue.
If you find a match, you can use the "subscribe" button to get notified on
updates. Do _not_ leave random "+1" or "I have this too" comments, as they
only clutter the discussion, and don't help resolving it. However, if you
have ways to reproduce the issue or have additional information that may help
resolving the issue, please leave a comment.

## Writing Good Bug Reports and Feature Requests

Please file a single issue per problem and feature request. Do not file combo
issues. Please do not submit multiple comments on a single issue - write your
issue with all the environmental information and reproduction steps so that an
engineer can reproduce it.

The community wants to help you find a solution to your problem, but every
problem is unique. In order for an engineer to help resolve your issue, they
need to be able to reproduce it. We put the product through extensive manual
and automated QA for every release, and verify all of its functionality. Any
feature that was previously working in a release that is no longer working is
marked as a severity/blocker for immediate review.

This means that if you are encountering an error, it is likely due to a unique
configuration of your system. Reproducing your specific error may require
significant information about your system and environment. Help us in advance
by providing a complete assessment of your system and the steps necessary to
reproduce the issue.

Therefore:

- The details of your environment including OS version, Python version.
- Provide reproducible steps, what the result of the steps was, and what you
  would have expected.
- A detailed description of the behavior that you expect.

## Development Setup

This project supports a dual setup for development: **Dev Containers** for an
isolated development environment in VS Code and **Devbox** for consistent
tooling when working in an external terminal. Follow the steps below to set up
your environment.

### Using Devbox

Devbox ensures consistent tooling and dependencies when working outside of VS
Code, such as in an external terminal.

1. **Install Devbox**
   - Follow the instructions to [install Devbox](https://www.jetify.com/devbox/docs/installing_devbox/).

2. **Install `direnv`**
   - Install `direnv` using your OS package manager. Refer to the [installation
     guide](https://direnv.net/docs/installation.html#from-system-packages).

3. **Hook `direnv` into Your Shell**
   - Follow the steps to [hook `direnv` into your shell](https://direnv.net/docs/hook.html).

4. **Load Environment**
   - At the top-level of your project, run:
     ```sh
     direnv allow
     ```
   - The next time you launch your terminal and enter the project directory,
     `direnv` will automatically load the Devbox environment.

5. **Install Dependencies**
   - Run:
     ```sh
     make install
     ```

6. **Start Environment**
   - Start the development environment with:
     ```sh
     make shell
     ```
   - This will launch a preconfigured Tmux session. Refer to the
     [.tmuxinator.yml](.tmuxinator.yml) file for details.

### Key Notes

- **Dev Containers** are ideal for development within VS Code, providing an
  isolated and consistent environment with preconfigured debug launchers.
- **Devbox** ensures consistent tooling and dependencies when working in an
  external terminal, complementing the Dev Container setup.
- Both setups share the same `make install` and `make shell` commands, ensuring
  consistency across environments.

By using both Dev Containers and Devbox, you get the best of both worlds: a
seamless development experience in VS Code and consistent tooling in your
terminal.

## Makefile Targets

Please see the [Makefile](Makefile) for the full list of targets.

## Contribute

Contributions to Oremi Akọrin are welcome. Here is how you can
contribute:

1. [Submit bugs or a feature request](https://gitlab.com/demsking/oremi-akorin/issues)
   and help us verify fixes as they are checked in
2. Create your working branch from the `dev` branch:
   `git checkout dev -b feature/my-awesome-feature`
3. Write code for a bug fix or for your new awesome feature
4. Write test cases for your changes
5. [Submit merge requests](https://gitlab.com/demsking/oremi-akorin/merge_requests)
   for bug fixes and features and discuss existing proposals

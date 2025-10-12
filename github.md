Connect Your Local Project to GitHub

Link your local project docker-reactjs-sample to the GitHub repository you just created by running the following command from your project root:

   $ git remote set-url origin https://github.com/{your-username}/{your-repository-name}.git
   
To confirm that your local project is correctly connected to the remote GitHub repository, run:


 git remote -v
 
You should see output similar to:


origin  https://github.com/{your-username}/{your-repository-name}.git (fetch)
origin  https://github.com/{your-username}/{your-repository-name}.git (push)
This confirms that your local repository is properly linked and ready to push your source code to GitHub.

Push Your Source Code to GitHub

Follow these steps to commit and push your local project to your GitHub repository:

Stage all files for commit.


 git add -A
This command stages all changes — including new, modified, and deleted files — preparing them for commit.

Commit your changes.


 git commit -m "Initial commit"
This command creates a commit that snapshots the staged changes with a descriptive message.

Push the code to the main branch.


 git push -u origin main
This command pushes your local commits to the main branch of the remote GitHub repository and sets the upstream branch.

Once completed, your code will be available on GitHub, and any GitHub Actions workflow you’ve configured will run automatically.

Note


To maintain code quality and prevent accidental direct pushes, enable branch protection rules:

Navigate to your GitHub repo → Settings → Branches.
Under Branch protection rules, click Add rule.
Specify main as the branch name.
Enable options like:
Require a pull request before merging.
Require status checks to pass before merging.
This ensures that only tested and reviewed code is merged into main branch.

https://docs.docker.com/guides/reactjs/configure-github-actions/
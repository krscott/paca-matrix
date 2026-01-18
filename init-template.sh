#!/usr/bin/env sh
set -eu

if [ $# -ne 1 ]; then
	echo "Usage: $(basename "$0") PROJ_NAME"
	exit 1
fi

if test -n "$(git status --porcelain)"; then
	echo "Git is dirty. Commit or stash changes."
	exit 2
fi

proj="$1"

# Generate project name variations for different contexts:
# - proj_flat: Binary/command name (no separators) - e.g., "pystart"
# - proj_hyphen: PyPI package name, git repo name - e.g., "py-start"
# - proj_underscore: Python module/package name - e.g., "py_start"
proj_flat=$(echo "$proj" | tr -d '_' | tr -d '-')
proj_hyphen=$(echo "$proj" | tr '_' '-')
proj_underscore=$(echo "$proj" | tr '-' '_')

proj_upper=$(echo "$proj_flat" | tr '[:lower:]' '[:upper:]')

cd "$(dirname "$(readlink -f -- "$0")")"

for file in $(git ls-files | grep -v 'init-template.sh'); do
	if [ -e "$file" ]; then
		echo "Processing: $file"
		sed -i "s/pystart/$proj_flat/g" "$file"
		sed -i "s/py-start/$proj_hyphen/g" "$file"
		sed -i "s/py_start/$proj_underscore/g" "$file"
		sed -i "s/PYSTART/$proj_upper/g" "$file"
	fi
done

echo "Renaming files"
mv py_start "${proj_underscore}"

echo "Deleting init script"
rm .github/workflows/init-template-test.yml
rm -- "$0"

echo "Removing LICENSE - visit https://choosealicense.com to get a new one"
rm LICENSE

if git config user.name >/dev/null; then
	git add .
	git commit -m "Init template"
fi

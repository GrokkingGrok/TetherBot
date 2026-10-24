# User-session install helpers. The bridge itself is not built with make.
.PHONY: install-extension lint-js

install-extension:
	./scripts/install-extension.sh

# GNOME Shell extension JavaScript. npm ci keeps the ESLint install matched
# to package-lock.json. The extension does not depend on these packages.
lint-js:
	npm ci --ignore-scripts
	npm run lint:js

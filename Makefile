# User-session install helpers. The bridge itself is not built with make.
.PHONY: install-extension lint-js restart-window

install-extension:
	./scripts/install-extension.sh

# One window service. Templated app-…@N units are leftovers from a double start.
restart-window:
	-systemctl --user stop tetherbot-window.service
	-systemctl --user stop app-io.github.grokkinggrok.TetherBot@0.service
	-systemctl --user stop app-io.github.grokkinggrok.TetherBot@1.service
	-systemctl --user reset-failed tetherbot-window.service
	systemctl --user start tetherbot-window.service

# GNOME Shell extension JavaScript. npm ci keeps the ESLint install matched
# to package-lock.json. The extension does not depend on these packages.
lint-js:
	npm ci --ignore-scripts
	npm run lint:js

# This plugin loads icons directly from disk paths for simplicity.
# The accompanying resources.qrc file is provided so the resources can be
# compiled later with pyrcc5 or pyside6-rcc if a compiled Qt resource bundle
# is preferred for deployment.


def qInitResources():
    return True


def qCleanupResources():
    return True

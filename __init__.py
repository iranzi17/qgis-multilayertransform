def classFactory(iface):
    """Load MultiLayerTransform plugin."""
    from .multilayer_transform import MultiLayerTransformPlugin

    return MultiLayerTransformPlugin(iface)

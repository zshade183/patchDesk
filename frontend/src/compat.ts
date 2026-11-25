// Qt 5 WebEngine targets Chromium 87, which predates Object.hasOwn.
if (!Object.hasOwn) {
  Object.defineProperty(Object, "hasOwn", {
    configurable: true,
    writable: true,
    value: (object: object, key: PropertyKey) => Object.prototype.hasOwnProperty.call(object, key),
  });
}

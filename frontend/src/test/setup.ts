import '@testing-library/jest-dom/vitest'

// jsdom does not implement scrollIntoView; the assistant page calls it to
// keep the latest message in view.
Element.prototype.scrollIntoView = () => {}

// jsdom does not implement ResizeObserver, which Radix ScrollArea uses.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver

// jsdom does not implement the Pointer Events capture API, which Radix Select/Dialog use.
Element.prototype.hasPointerCapture = () => false
Element.prototype.setPointerCapture = () => {}
Element.prototype.releasePointerCapture = () => {}

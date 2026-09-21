import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

type RenderEntry = {
  component: React.ElementType;
  props?: Record<string, unknown>;
  children?: React.ReactNode;
};

/**
 * Render Vite SSR-loaded components with the React/ReactDOM instance from the
 * same Vite module graph. Mixing a component loaded through vite.ssrLoadModule
 * with a renderer imported directly by Node can create two React runtimes and
 * trigger an "Invalid hook call" even when the component is correct.
 */
export function renderComponentToStaticMarkup(
  component: React.ElementType,
  props: Record<string, unknown> = {},
  children?: React.ReactNode,
): string {
  return renderToStaticMarkup(React.createElement(component, props, children));
}

export function renderComponentListToStaticMarkup(entries: RenderEntry[]): string {
  return renderToStaticMarkup(
    React.createElement(
      React.Fragment,
      null,
      ...entries.map((entry, index) =>
        React.createElement(entry.component, { key: index, ...(entry.props || {}) }, entry.children),
      ),
    ),
  );
}

export function renderNestedComponentToStaticMarkup(
  parent: React.ElementType,
  parentProps: Record<string, unknown>,
  child: React.ElementType,
  childProps: Record<string, unknown> = {},
): string {
  return renderToStaticMarkup(
    React.createElement(parent, parentProps, React.createElement(child, childProps)),
  );
}

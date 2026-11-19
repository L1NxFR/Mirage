import DOMPurify from 'dompurify';

// Retain only CSSOM-parsed text/background colors on a mark. Other inline
// styles stay forbidden, including layout rules and background images.
function keepHighlightColors(node, attribute) {
  if (node.nodeName !== 'MARK' || attribute.attrName !== 'style') return;
  const background = node.style.backgroundColor;
  const color = node.style.color;
  node.style.cssText = '';
  if (background) node.style.backgroundColor = background;
  if (color) node.style.color = color;
  attribute.attrValue = node.getAttribute('style') || '';
  attribute.forceKeepAttr = Boolean(background || color);
}

export function sanitizePreview(html) {
  DOMPurify.addHook('uponSanitizeAttribute', keepHighlightColors);
  try {
    return DOMPurify.sanitize(html, { RETURN_DOM_FRAGMENT: true,
      FORBID_TAGS: ['style', 'form', 'iframe'], FORBID_ATTR: ['style'] });
  } finally {
    DOMPurify.removeHook('uponSanitizeAttribute', keepHighlightColors);
  }
}

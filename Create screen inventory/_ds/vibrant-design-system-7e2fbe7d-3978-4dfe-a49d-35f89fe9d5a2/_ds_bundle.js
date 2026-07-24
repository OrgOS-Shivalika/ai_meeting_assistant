/* @ds-bundle: {"format":3,"namespace":"VibrantDesignSystem_7e2fbe","components":[{"name":"FeatureCard","sourcePath":"components/cards/FeatureCard.jsx"},{"name":"StatCard","sourcePath":"components/cards/StatCard.jsx"},{"name":"Avatar","sourcePath":"components/core/Avatar.jsx"},{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"Input","sourcePath":"components/core/Input.jsx"},{"name":"Switch","sourcePath":"components/core/Switch.jsx"},{"name":"Tabs","sourcePath":"components/core/Tabs.jsx"}],"sourceHashes":{"components/cards/FeatureCard.jsx":"f161b9d35045","components/cards/StatCard.jsx":"14889d58b44f","components/core/Avatar.jsx":"aaf4240651c9","components/core/Badge.jsx":"2f6bb8d4033a","components/core/Button.jsx":"74ed5aec0c39","components/core/Input.jsx":"ccb221208365","components/core/Switch.jsx":"341de1bab7a0","components/core/Tabs.jsx":"13bd74b53513","ui_kits/app/AnalyticsScreen.jsx":"7c88768b5c18","ui_kits/app/CohortsScreen.jsx":"f4bcb1cc6b7e","ui_kits/app/ContactsScreen.jsx":"aaef04694913","ui_kits/app/Icon.jsx":"487c0d532f82","ui_kits/app/InboxScreen.jsx":"ee2c5acc18bb","ui_kits/app/IntegrationsScreen.jsx":"104708ab0088","ui_kits/app/PipelineScreen.jsx":"f37f5441787f","ui_kits/app/Sidebar.jsx":"4a4977656415","ui_kits/app/TeamScreen.jsx":"167874bf6c5b","ui_kits/app/Topbar.jsx":"8a917eaea197","ui_kits/app/data.jsx":"7bd0c5a22d9d","ui_kits/merchant/DashboardScreen.jsx":"bfae327517d0","ui_kits/merchant/MerchantNav.jsx":"982e174f443e","ui_kits/merchant/Screens.jsx":"2797d59c6d87","ui_kits/merchant/data.jsx":"585992cb089e","ui_kits/storefront/CartScreen.jsx":"7cf1d89fa593","ui_kits/storefront/HomeScreen.jsx":"98a72964f8d5","ui_kits/storefront/ProductScreen.jsx":"0db5a2d4178c","ui_kits/storefront/StoreChrome.jsx":"d1c7f7ec3b9a","ui_kits/storefront/data.jsx":"e1b117b7019f"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.VibrantDesignSystem_7e2fbe = window.VibrantDesignSystem_7e2fbe || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/cards/FeatureCard.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Appu FeatureCard — the saturated single-color card that carries the brand's
 * voltage. Pick a color per feature (pink/teal/lavender/peach/ochre/cream),
 * add an eyebrow + title + body, and optionally embed a product fragment.
 */
function FeatureCard({
  color = 'pink',
  eyebrow = null,
  title,
  body,
  children,
  footer = null,
  style = {},
  ...rest
}) {
  const palette = {
    pink: {
      bg: 'var(--vb-pink)',
      fg: '#fff',
      soft: 'rgba(255,255,255,0.7)'
    },
    teal: {
      bg: 'var(--vb-teal)',
      fg: '#fff',
      soft: 'rgba(255,255,255,0.6)'
    },
    lavender: {
      bg: 'var(--vb-lavender)',
      fg: 'var(--vb-ink)',
      soft: 'rgba(10,10,10,0.55)'
    },
    peach: {
      bg: 'var(--vb-peach)',
      fg: 'var(--vb-ink)',
      soft: 'rgba(10,10,10,0.55)'
    },
    ochre: {
      bg: 'var(--vb-ochre)',
      fg: 'var(--vb-ink)',
      soft: 'rgba(10,10,10,0.55)'
    },
    cream: {
      bg: 'var(--vb-surface-card)',
      fg: 'var(--vb-ink)',
      soft: 'var(--vb-muted)'
    }
  };
  const c = palette[color] || palette.pink;
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      background: c.bg,
      color: c.fg,
      borderRadius: 'var(--radius-xl)',
      padding: 32,
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
      fontFamily: 'var(--font-sans)',
      boxShadow: color === 'cream' ? 'inset 0 0 0 1px var(--vb-hairline)' : 'none',
      ...style
    }
  }, rest), eyebrow ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontWeight: 600,
      letterSpacing: '1.5px',
      textTransform: 'uppercase',
      color: c.soft
    }
  }, eyebrow) : null, title ? /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontFamily: 'var(--font-display)',
      fontSize: 24,
      fontWeight: 600,
      letterSpacing: '-0.6px',
      lineHeight: 1.15
    }
  }, title) : null, body ? /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 15,
      lineHeight: 1.55,
      color: c.soft,
      maxWidth: '46ch'
    }
  }, body) : null, children ? /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 4
    }
  }, children) : null, footer ? /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 'auto',
      paddingTop: 8
    }
  }, footer) : null);
}
Object.assign(__ds_scope, { FeatureCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/cards/FeatureCard.jsx", error: String((e && e.message) || e) }); }

// components/cards/StatCard.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Appu StatCard — dashboard metric tile. Cream/white card with hairline,
 * a label, a large mono-ish value, and an optional up/down delta.
 */
function StatCard({
  label,
  value,
  delta = null,
  deltaDir = 'up',
  icon = null,
  accent = null,
  style = {},
  ...rest
}) {
  const up = deltaDir === 'up';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      background: 'var(--vb-canvas)',
      border: '1px solid var(--vb-hairline)',
      borderRadius: 'var(--radius-lg)',
      padding: 20,
      display: 'flex',
      flexDirection: 'column',
      gap: 12,
      fontFamily: 'var(--font-sans)',
      minWidth: 0,
      ...style
    }
  }, rest), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 600,
      color: 'var(--vb-muted)',
      letterSpacing: '-0.1px'
    }
  }, label), icon ? /*#__PURE__*/React.createElement("span", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 'var(--radius-sm)',
      background: accent || 'var(--vb-surface-card)',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: accent ? '#fff' : 'var(--vb-ink)',
      flex: 'none'
    }
  }, icon) : null), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 32,
      fontWeight: 600,
      letterSpacing: '-1px',
      color: 'var(--vb-ink)',
      lineHeight: 1
    }
  }, value), delta ? /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 3,
      fontSize: 13,
      fontWeight: 600,
      color: up ? '#157a3a' : 'var(--vb-error)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12
    }
  }, up ? '▲' : '▼'), delta) : null));
}
Object.assign(__ds_scope, { StatCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/cards/StatCard.jsx", error: String((e && e.message) || e) }); }

// components/core/Avatar.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Appu Avatar — circular initials or image. Cream/brand tint backgrounds,
 * optional status ring. For contacts, agents, and the AI service identity.
 */
function Avatar({
  name = '',
  src = null,
  size = 40,
  tone = 'auto',
  square = false,
  ...rest
}) {
  const palette = ['var(--vb-pink)', 'var(--vb-teal)', 'var(--vb-lavender)', 'var(--vb-peach)', 'var(--vb-ochre)', 'var(--vb-mint)'];
  const initials = name.split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase();
  let bg = tone;
  if (tone === 'auto') {
    let h = 0;
    for (let i = 0; i < name.length; i++) h = h * 31 + name.charCodeAt(i) >>> 0;
    bg = palette[h % palette.length];
  }
  const darkBgs = ['var(--vb-teal)', 'var(--vb-pink)'];
  const fg = darkBgs.includes(bg) ? '#fff' : 'var(--vb-ink)';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      width: size,
      height: size,
      borderRadius: square ? 'var(--radius-md)' : '50%',
      background: src ? 'var(--vb-surface-card)' : bg,
      color: fg,
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'var(--font-sans)',
      fontWeight: 600,
      fontSize: Math.round(size * 0.38),
      letterSpacing: '-0.3px',
      overflow: 'hidden',
      flex: 'none',
      userSelect: 'none'
    }
  }, rest), src ? /*#__PURE__*/React.createElement("img", {
    src: src,
    alt: name,
    style: {
      width: '100%',
      height: '100%',
      objectFit: 'cover'
    }
  }) : initials);
}
Object.assign(__ds_scope, { Avatar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Avatar.jsx", error: String((e && e.message) || e) }); }

// components/core/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Appu Badge — small pill label. Cream by default; semantic and brand tones.
 * Optional leading dot for status. 13px / 500.
 */
function Badge({
  tone = 'neutral',
  dot = false,
  children,
  style = {},
  ...rest
}) {
  const tones = {
    neutral: {
      bg: 'var(--vb-surface-card)',
      fg: 'var(--vb-ink)',
      dot: 'var(--vb-muted)'
    },
    ink: {
      bg: 'var(--vb-ink)',
      fg: 'var(--vb-on-ink)',
      dot: 'var(--vb-mint)'
    },
    pink: {
      bg: 'color-mix(in oklch, var(--vb-pink) 18%, white)',
      fg: '#a01f56',
      dot: 'var(--vb-pink)'
    },
    teal: {
      bg: 'color-mix(in oklch, var(--vb-teal) 14%, white)',
      fg: 'var(--vb-teal)',
      dot: 'var(--vb-teal)'
    },
    lavender: {
      bg: 'color-mix(in oklch, var(--vb-lavender) 30%, white)',
      fg: '#5b4a8a',
      dot: 'var(--vb-lavender)'
    },
    success: {
      bg: 'color-mix(in oklch, var(--vb-success) 16%, white)',
      fg: '#157a3a',
      dot: 'var(--vb-success)'
    },
    warning: {
      bg: 'color-mix(in oklch, var(--vb-warning) 18%, white)',
      fg: '#8a5a06',
      dot: 'var(--vb-warning)'
    },
    error: {
      bg: 'color-mix(in oklch, var(--vb-error) 14%, white)',
      fg: '#b4231f',
      dot: 'var(--vb-error)'
    }
  };
  const t = tones[tone] || tones.neutral;
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      fontFamily: 'var(--font-sans)',
      fontSize: 13,
      fontWeight: 500,
      lineHeight: 1,
      letterSpacing: '-0.1px',
      padding: '5px 12px',
      borderRadius: 'var(--radius-pill)',
      background: t.bg,
      color: t.fg,
      whiteSpace: 'nowrap',
      ...style
    }
  }, rest), dot ? /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: t.dot,
      flex: 'none'
    }
  }) : null, children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Appu Button — the brand's primary action element.
 * Ink-filled primary, cream secondary, white on-color (for saturated cards),
 * ghost, and inline link. Rounded 12px (radius-md), 44px tall at md.
 */
function Button({
  variant = 'primary',
  size = 'md',
  leadingIcon = null,
  trailingIcon = null,
  disabled = false,
  fullWidth = false,
  children,
  style = {},
  ...rest
}) {
  const sizes = {
    sm: {
      height: 36,
      padding: '0 14px',
      fontSize: 13,
      radius: 'var(--radius-sm)',
      gap: 6
    },
    md: {
      height: 44,
      padding: '0 20px',
      fontSize: 14,
      radius: 'var(--radius-md)',
      gap: 8
    },
    lg: {
      height: 52,
      padding: '0 26px',
      fontSize: 15,
      radius: 'var(--radius-md)',
      gap: 8
    }
  };
  const s = sizes[size] || sizes.md;
  const variants = {
    primary: {
      background: 'var(--vb-ink)',
      color: 'var(--vb-on-ink)',
      border: '1px solid var(--vb-ink)'
    },
    secondary: {
      background: 'var(--vb-canvas)',
      color: 'var(--vb-ink)',
      border: '1px solid var(--vb-hairline)'
    },
    onColor: {
      background: 'var(--vb-canvas)',
      color: 'var(--vb-ink)',
      border: '1px solid transparent'
    },
    ghost: {
      background: 'transparent',
      color: 'var(--vb-ink)',
      border: '1px solid transparent'
    },
    link: {
      background: 'transparent',
      color: 'var(--vb-ink)',
      border: '1px solid transparent',
      textDecoration: 'underline',
      textUnderlineOffset: 3,
      height: 'auto',
      padding: 0
    }
  };
  const v = variants[variant] || variants.primary;
  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: s.gap,
    fontFamily: 'var(--font-sans)',
    fontWeight: 600,
    fontSize: v.fontSize || s.fontSize,
    letterSpacing: '-0.1px',
    lineHeight: 1,
    height: v.height || s.height,
    padding: v.padding !== undefined ? v.padding : s.padding,
    borderRadius: s.radius,
    cursor: disabled ? 'not-allowed' : 'pointer',
    width: fullWidth ? '100%' : 'auto',
    whiteSpace: 'nowrap',
    transition: 'background 140ms ease, opacity 140ms ease, transform 80ms ease',
    background: v.background,
    color: v.color,
    border: v.border,
    textDecoration: v.textDecoration,
    textUnderlineOffset: v.textUnderlineOffset,
    ...(disabled ? {
      background: variant === 'primary' ? 'var(--vb-ink-disabled)' : 'var(--vb-canvas)',
      color: 'var(--vb-muted-soft)',
      borderColor: 'var(--vb-hairline)',
      cursor: 'not-allowed'
    } : {}),
    ...style
  };
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    disabled: disabled,
    style: base
  }, rest), leadingIcon ? /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex'
    }
  }, leadingIcon) : null, children, trailingIcon ? /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex'
    }
  }, trailingIcon) : null);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Appu Input — text field. Cream fill, hairline border thickening to ink
 * on focus. 44px tall, radius-md. Optional label, leading icon, and hint/error.
 */
function Input({
  label = null,
  hint = null,
  error = null,
  leadingIcon = null,
  id,
  style = {},
  ...rest
}) {
  const [focused, setFocused] = React.useState(false);
  const inputId = id || React.useId();
  const borderColor = error ? 'var(--vb-error)' : focused ? 'var(--vb-ink)' : 'var(--vb-hairline)';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      fontFamily: 'var(--font-sans)'
    }
  }, label ? /*#__PURE__*/React.createElement("label", {
    htmlFor: inputId,
    style: {
      fontSize: 14,
      fontWeight: 600,
      color: 'var(--vb-body-strong)'
    }
  }, label) : null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      height: 44,
      padding: '0 14px',
      background: 'var(--vb-canvas)',
      border: `1px solid ${borderColor}`,
      borderRadius: 'var(--radius-md)',
      transition: 'border-color 140ms ease, box-shadow 140ms ease',
      boxShadow: focused && !error ? '0 0 0 3px var(--focus-ring)' : 'none',
      ...style
    }
  }, leadingIcon ? /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      color: 'var(--vb-muted)',
      flex: 'none'
    }
  }, leadingIcon) : null, /*#__PURE__*/React.createElement("input", _extends({
    id: inputId,
    onFocus: e => {
      setFocused(true);
      rest.onFocus && rest.onFocus(e);
    },
    onBlur: e => {
      setFocused(false);
      rest.onBlur && rest.onBlur(e);
    }
  }, rest, {
    style: {
      flex: 1,
      border: 'none',
      outline: 'none',
      background: 'transparent',
      fontFamily: 'var(--font-sans)',
      fontSize: 16,
      color: 'var(--vb-ink)',
      minWidth: 0
    }
  }))), error ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      color: 'var(--vb-error)'
    }
  }, error) : hint ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      color: 'var(--vb-muted)'
    }
  }, hint) : null);
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Input.jsx", error: String((e && e.message) || e) }); }

// components/core/Switch.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Appu Switch — toggle for autonomy policies, consent, and settings.
 * Ink track when on, hairline track when off. Controlled or uncontrolled.
 */
function Switch({
  checked,
  defaultChecked = false,
  onChange,
  disabled = false,
  label = null,
  size = 'md',
  ...rest
}) {
  const [internal, setInternal] = React.useState(defaultChecked);
  const on = checked !== undefined ? checked : internal;
  const dims = size === 'sm' ? {
    w: 36,
    h: 20,
    k: 16
  } : {
    w: 46,
    h: 26,
    k: 22
  };
  const toggle = () => {
    if (disabled) return;
    if (checked === undefined) setInternal(!on);
    onChange && onChange(!on);
  };
  const control = /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    role: "switch",
    "aria-checked": on,
    onClick: toggle,
    disabled: disabled,
    style: {
      position: 'relative',
      width: dims.w,
      height: dims.h,
      flex: 'none',
      borderRadius: 'var(--radius-pill)',
      border: 'none',
      cursor: disabled ? 'not-allowed' : 'pointer',
      background: on ? 'var(--vb-ink)' : 'var(--vb-hairline)',
      opacity: disabled ? 0.5 : 1,
      transition: 'background 160ms ease',
      padding: 0
    }
  }, rest), /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      top: (dims.h - dims.k) / 2,
      left: on ? dims.w - dims.k - (dims.h - dims.k) / 2 : (dims.h - dims.k) / 2,
      width: dims.k,
      height: dims.k,
      borderRadius: '50%',
      background: '#fff',
      boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
      transition: 'left 160ms cubic-bezier(0.34,1.4,0.5,1)'
    }
  }));
  if (!label) return control;
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 10,
      cursor: disabled ? 'not-allowed' : 'pointer',
      fontFamily: 'var(--font-sans)',
      fontSize: 14,
      fontWeight: 500,
      color: 'var(--vb-body-strong)'
    }
  }, control, label);
}
Object.assign(__ds_scope, { Switch });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Switch.jsx", error: String((e && e.message) || e) }); }

// components/core/Tabs.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Appu Tabs — pill-style category tabs. Active tab gets cream-card fill +
 * ink text; inactive are transparent + muted. Controlled or uncontrolled.
 */
function Tabs({
  tabs = [],
  value,
  defaultValue,
  onChange,
  style = {},
  ...rest
}) {
  const [internal, setInternal] = React.useState(defaultValue ?? (tabs[0] && tabs[0].id));
  const active = value !== undefined ? value : internal;
  const select = id => {
    if (value === undefined) setInternal(id);
    onChange && onChange(id);
  };
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: 'inline-flex',
      gap: 4,
      padding: 4,
      background: 'var(--vb-surface-soft)',
      borderRadius: 'var(--radius-pill)',
      ...style
    },
    role: "tablist"
  }, rest), tabs.map(t => {
    const on = t.id === active;
    return /*#__PURE__*/React.createElement("button", {
      key: t.id,
      role: "tab",
      "aria-selected": on,
      onClick: () => select(t.id),
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
        border: 'none',
        cursor: 'pointer',
        fontFamily: 'var(--font-sans)',
        fontSize: 14,
        fontWeight: on ? 600 : 500,
        letterSpacing: '-0.1px',
        padding: '8px 16px',
        borderRadius: 'var(--radius-pill)',
        background: on ? 'var(--vb-canvas)' : 'transparent',
        color: on ? 'var(--vb-ink)' : 'var(--vb-muted)',
        boxShadow: on ? 'var(--shadow-soft)' : 'none',
        transition: 'background 140ms ease, color 140ms ease'
      }
    }, t.label, t.count !== undefined ? /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        fontWeight: 600,
        color: on ? 'var(--vb-muted)' : 'var(--vb-muted-soft)'
      }
    }, t.count) : null);
  }));
}
Object.assign(__ds_scope, { Tabs });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Tabs.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/AnalyticsScreen.jsx
try { (() => {
// Appu CRM — Analytics (per-agent scorecards + team table, mirrors /v1/reports/agents).
(function () {
  const {
    StatCard,
    Badge,
    Avatar,
    Switch,
    Button,
    Tabs
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.VBDATA;
  const money = v => '$' + (v / 1000).toFixed(0) + 'k';
  const pct = v => Math.round(v * 100) + '%';
  function Analytics() {
    const t = D.totals;
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement(Tabs, {
      defaultValue: "30",
      tabs: [{
        id: '7',
        label: 'Last 7d'
      }, {
        id: '30',
        label: 'Last 30d'
      }, {
        id: '90',
        label: 'Last 90d'
      }],
      style: {
        display: 'flex'
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '7px 14px',
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Shuffle",
      size: 15,
      color: "var(--vb-teal)"
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, "Auto lead assignment"), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        color: 'var(--vb-muted)'
      }
    }, "\xB7 round robin"), /*#__PURE__*/React.createElement(Switch, {
      defaultChecked: true,
      size: "sm"
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 14
      }
    }, /*#__PURE__*/React.createElement(StatCard, {
      label: "Pipeline value",
      value: money(t.pipeline),
      delta: "14%",
      deltaDir: "up",
      icon: /*#__PURE__*/React.createElement(Icon, {
        name: "TrendingUp",
        size: 16,
        color: "#fff"
      }),
      accent: "var(--vb-pink)"
    }), /*#__PURE__*/React.createElement(StatCard, {
      label: "Won / lost",
      value: t.won + ' / ' + t.lost,
      delta: money(t.wonValue),
      deltaDir: "up",
      icon: /*#__PURE__*/React.createElement(Icon, {
        name: "Trophy",
        size: 16,
        color: "#fff"
      }),
      accent: "var(--vb-teal)"
    }), /*#__PURE__*/React.createElement(StatCard, {
      label: "New leads",
      value: t.newLeads,
      delta: "9%",
      deltaDir: "up",
      icon: /*#__PURE__*/React.createElement(Icon, {
        name: "UserPlus",
        size: 16,
        color: "#fff"
      }),
      accent: "var(--vb-lavender)"
    }), /*#__PURE__*/React.createElement(StatCard, {
      label: "AI messages",
      value: t.aiMessages,
      delta: 'of ' + t.msgs,
      deltaDir: "up",
      icon: /*#__PURE__*/React.createElement(Icon, {
        name: "Bot",
        size: 16,
        color: "#fff"
      }),
      accent: "var(--vb-ochre)"
    })), /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '14px 18px',
        borderBottom: '1px solid var(--vb-hairline)',
        display: 'flex',
        alignItems: 'center',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, "Agent performance"), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      trailingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Download",
        size: 14,
        color: "var(--vb-ink)"
      })
    }, "Export")), /*#__PURE__*/React.createElement("table", {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        fontFamily: 'var(--font-sans)'
      }
    }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.5px',
        textTransform: 'uppercase',
        color: 'var(--vb-muted)'
      }
    }, ['Member', 'Role', 'Leads', 'Opps', 'Pipeline', 'Won', 'Win rate', 'Convos', 'Calls', 'Resp'].map((h, i) => /*#__PURE__*/React.createElement("th", {
      key: h,
      style: {
        textAlign: i < 2 ? 'left' : 'right',
        padding: i === 0 ? '10px 18px' : '10px 12px',
        fontWeight: 600
      }
    }, h)))), /*#__PURE__*/React.createElement("tbody", null, D.agents.map(a => /*#__PURE__*/React.createElement("tr", {
      key: a.name,
      style: {
        borderTop: '1px solid var(--vb-hairline-soft)'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 18px'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 9
      }
    }, /*#__PURE__*/React.createElement(Avatar, {
      name: a.name,
      size: 28
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, a.name))), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px'
      }
    }, /*#__PURE__*/React.createElement(Badge, null, a.role.replace('_', ' '))), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontSize: 13,
        color: 'var(--vb-body)'
      }
    }, a.leads, " ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-muted-soft)'
      }
    }, "(+", a.newLeads, ")")), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontSize: 13,
        color: 'var(--vb-body)'
      }
    }, a.opps), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontFamily: 'var(--font-mono)',
        fontSize: 12.5,
        color: 'var(--vb-ink)'
      }
    }, money(a.pipeline)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontSize: 13,
        fontWeight: 600,
        color: '#157a3a'
      }
    }, a.won, " / ", money(a.wonValue)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontFamily: 'var(--font-mono)',
        fontSize: 12.5,
        color: 'var(--vb-ink)'
      }
    }, pct(a.winRate)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontSize: 13,
        color: 'var(--vb-body)'
      }
    }, a.convos), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontSize: 13,
        color: 'var(--vb-body)'
      }
    }, a.calls, " ", /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-muted-soft)'
      }
    }, "(", a.callsConn, ")")), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontFamily: 'var(--font-mono)',
        fontSize: 12.5,
        color: 'var(--vb-muted)'
      }
    }, a.resp, "m"))), /*#__PURE__*/React.createElement("tr", {
      style: {
        borderTop: '1px solid var(--vb-hairline)',
        background: 'var(--vb-surface-soft)'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 18px',
        fontSize: 13.5,
        fontWeight: 700,
        color: 'var(--vb-ink)'
      }
    }, "Total"), /*#__PURE__*/React.createElement("td", null), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontSize: 13,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, t.leads), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontSize: 13,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, t.opps), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontFamily: 'var(--font-mono)',
        fontSize: 12.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, money(t.pipeline)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px',
        textAlign: 'right',
        fontSize: 13,
        fontWeight: 700,
        color: '#157a3a'
      }
    }, t.won, " / ", money(t.wonValue)), /*#__PURE__*/React.createElement("td", {
      colSpan: 4
    }))))));
  }
  window.VBAnalytics = Analytics;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/AnalyticsScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/CohortsScreen.jsx
try { (() => {
// Appu CRM — Cohorts (mirrors /v1/cohorts: name, kind, members).
(function () {
  const {
    FeatureCard,
    Badge,
    Button
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.VBDATA;
  const kindIcon = {
    lookalike: 'Radar',
    cluster: 'Boxes',
    churn: 'TrendingDown'
  };
  function Cohorts() {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 13.5,
        color: 'var(--vb-muted)'
      }
    }, "ML-derived groups, refreshed on each scoring run."), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Sparkles",
        size: 14,
        color: "#fff"
      })
    }, "Build cohort")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: 14
      }
    }, D.cohorts.map(c => /*#__PURE__*/React.createElement(FeatureCard, {
      key: c.name,
      color: c.color,
      style: {
        padding: 22,
        gap: 10
      },
      footer: /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginTop: 6
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          display: 'inline-flex',
          alignItems: 'center',
          gap: 7,
          fontSize: 13,
          fontWeight: 600
        }
      }, /*#__PURE__*/React.createElement(Icon, {
        name: kindIcon[c.kind],
        size: 15,
        color: "currentColor"
      }), c.kind), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
        style: {
          fontFamily: 'var(--font-display)',
          fontSize: 28,
          fontWeight: 600,
          letterSpacing: '-1px'
        }
      }, c.members), " ", /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 13,
          opacity: 0.75
        }
      }, "members")))
    }, /*#__PURE__*/React.createElement("h3", {
      style: {
        margin: '2px 0 2px',
        fontFamily: 'var(--font-display)',
        fontSize: 20,
        fontWeight: 600,
        letterSpacing: '-0.5px',
        lineHeight: 1.15
      }
    }, c.name), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 13.5,
        lineHeight: 1.45,
        opacity: 0.85
      }
    }, c.desc)))));
  }
  window.VBCohorts = Cohorts;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/CohortsScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/ContactsScreen.jsx
try { (() => {
// Appu CRM — Contacts (mirrors /v1/contacts: score, owner, enrich, activity).
(function () {
  const {
    Badge,
    Avatar,
    Button,
    Input,
    Tabs
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.VBDATA;
  const statusTone = {
    qualified: 'success',
    nurturing: 'lavender',
    new: 'neutral'
  };
  function ScoreBar({
    score
  }) {
    if (score == null) return /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        color: 'var(--vb-muted-soft)'
      }
    }, "unscored");
    const c = score >= 85 ? 'var(--vb-pink)' : score >= 70 ? 'var(--vb-ochre)' : 'var(--vb-lavender)';
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 50,
        height: 6,
        borderRadius: 4,
        background: 'var(--vb-hairline)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: score + '%',
        height: '100%',
        background: c
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, score));
  }
  function Contacts() {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        padding: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'flex-end',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 220
      }
    }, /*#__PURE__*/React.createElement(Input, {
      label: "Name",
      placeholder: "New contact"
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        width: 240
      }
    }, /*#__PURE__*/React.createElement(Input, {
      label: "Email",
      placeholder: "name@company.com"
    })), /*#__PURE__*/React.createElement(Button, {
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Plus",
        size: 15,
        color: "#fff"
      })
    }, "Create contact"))), /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '14px 18px',
        borderBottom: '1px solid var(--vb-hairline)'
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, "Contacts"), /*#__PURE__*/React.createElement(Tabs, {
      defaultValue: "all",
      tabs: [{
        id: 'all',
        label: 'All',
        count: 1284
      }, {
        id: 'hot',
        label: 'Hot'
      }, {
        id: 'unowned',
        label: 'Unassigned'
      }],
      style: {
        display: 'flex'
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "secondary",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Sparkles",
        size: 14,
        color: "var(--vb-ink)"
      })
    }, "Score all")), /*#__PURE__*/React.createElement("table", {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        fontFamily: 'var(--font-sans)'
      }
    }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.6px',
        textTransform: 'uppercase',
        color: 'var(--vb-muted)'
      }
    }, /*#__PURE__*/React.createElement("th", {
      style: {
        textAlign: 'left',
        padding: '10px 18px',
        fontWeight: 600
      }
    }, "Contact"), /*#__PURE__*/React.createElement("th", {
      style: {
        textAlign: 'left',
        padding: '10px 12px',
        fontWeight: 600
      }
    }, "Status"), /*#__PURE__*/React.createElement("th", {
      style: {
        textAlign: 'left',
        padding: '10px 12px',
        fontWeight: 600
      }
    }, "Lead score"), /*#__PURE__*/React.createElement("th", {
      style: {
        textAlign: 'left',
        padding: '10px 12px',
        fontWeight: 600
      }
    }, "Owner"), /*#__PURE__*/React.createElement("th", {
      style: {
        padding: '10px 18px'
      }
    }))), /*#__PURE__*/React.createElement("tbody", null, D.contacts.map(c => /*#__PURE__*/React.createElement("tr", {
      key: c.name,
      style: {
        borderTop: '1px solid var(--vb-hairline-soft)'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '11px 18px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement(Avatar, {
      name: c.name,
      size: 32
    }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, c.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted)'
      }
    }, c.company)))), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '11px 12px'
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: statusTone[c.status],
      dot: c.status === 'qualified'
    }, c.status)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '11px 12px'
      }
    }, /*#__PURE__*/React.createElement(ScoreBar, {
      score: c.score
    })), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '11px 12px'
      }
    }, c.owner ? /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7
      }
    }, /*#__PURE__*/React.createElement(Avatar, {
      name: c.owner,
      size: 22
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        color: 'var(--vb-body)'
      }
    }, c.owner.split(' ')[0])) : /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        color: 'var(--vb-muted-soft)'
      }
    }, "unassigned")), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '11px 18px',
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        gap: 4
      }
    }, /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Gauge",
        size: 14,
        color: "var(--vb-ink)"
      })
    }, "Score"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Database",
        size: 14,
        color: "var(--vb-ink)"
      })
    }, "Enrich"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Activity",
        size: 14,
        color: "var(--vb-ink)"
      })
    }, "Activity")))))))));
  }
  window.VBContacts = Contacts;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/ContactsScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/Icon.jsx
try { (() => {
// Lucide icon helper for Appu UI kits (UMD, no npm).
// Renders a Lucide icon node as an inline SVG React element.
(function () {
  function Icon(props) {
    const {
      name,
      size = 18,
      color = 'currentColor',
      strokeWidth = 2,
      style,
      ...rest
    } = props;
    const lib = window.lucide && (window.lucide.icons || window.lucide);
    const node = lib && lib[name];
    if (!node) {
      return React.createElement('span', {
        style: {
          display: 'inline-block',
          width: size,
          height: size,
          ...style
        }
      });
    }
    // Lucide UMD icon shape is a full IconNode triple: ["svg", attrs, [ [tag, attrs], ... ]].
    // Children are the third element; older shapes expose a flat children array.
    const childArr = Array.isArray(node[2]) ? node[2] : Array.isArray(node) && Array.isArray(node[0]) ? node : [];
    const children = childArr.map((c, i) => React.createElement(c[0], Object.assign({
      key: i
    }, c[1])));
    return React.createElement('svg', Object.assign({
      xmlns: 'http://www.w3.org/2000/svg',
      width: size,
      height: size,
      viewBox: '0 0 24 24',
      fill: 'none',
      stroke: color,
      strokeWidth: strokeWidth,
      strokeLinecap: 'round',
      strokeLinejoin: 'round',
      style: Object.assign({
        display: 'block',
        flex: 'none'
      }, style)
    }, rest), children);
  }
  window.Icon = Icon;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/Icon.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/InboxScreen.jsx
try { (() => {
// Appu CRM — Inbox (conversations + thread + context). Mirrors the real /v1/conversations UI.
(function () {
  const {
    Tabs,
    Avatar,
    Badge,
    Button,
    Switch
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.VBDATA;
  const chIcon = {
    WhatsApp: 'MessageCircle',
    Email: 'Mail',
    Web: 'Globe',
    Voice: 'Phone'
  };
  const stateTone = {
    open: 'teal',
    human: 'pink',
    resolved: 'success'
  };
  function Inbox() {
    const [sel, setSel] = React.useState(D.conversations[0].id);
    const conv = D.conversations.find(c => c.id === sel) || D.conversations[0];
    const aiOwned = conv.assignee === 'ai';
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        height: '100%',
        minHeight: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 326,
        flex: 'none',
        borderRight: '1px solid var(--vb-hairline)',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '14px 16px 10px'
      }
    }, /*#__PURE__*/React.createElement(Tabs, {
      defaultValue: "all",
      tabs: [{
        id: 'all',
        label: 'All',
        count: 4
      }, {
        id: 'ai',
        label: 'AI',
        count: 2
      }, {
        id: 'mine',
        label: 'Mine',
        count: 1
      }],
      style: {
        display: 'flex'
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        overflowY: 'auto',
        flex: 1
      }
    }, D.conversations.map(c => {
      const on = c.id === sel;
      return /*#__PURE__*/React.createElement("button", {
        key: c.id,
        onClick: () => setSel(c.id),
        style: {
          display: 'flex',
          gap: 11,
          width: '100%',
          textAlign: 'left',
          cursor: 'pointer',
          padding: '13px 16px',
          border: 'none',
          borderLeft: on ? '3px solid var(--vb-pink)' : '3px solid transparent',
          background: on ? 'var(--vb-surface-soft)' : 'transparent'
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          position: 'relative',
          flex: 'none'
        }
      }, /*#__PURE__*/React.createElement(Avatar, {
        name: c.name,
        size: 38
      }), /*#__PURE__*/React.createElement("span", {
        style: {
          position: 'absolute',
          right: -2,
          bottom: -2,
          width: 16,
          height: 16,
          borderRadius: '50%',
          background: '#fff',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 0 0 1.5px var(--vb-canvas)'
        }
      }, /*#__PURE__*/React.createElement(Icon, {
        name: chIcon[c.channel],
        size: 10,
        color: "var(--vb-ink)"
      }))), /*#__PURE__*/React.createElement("div", {
        style: {
          minWidth: 0,
          flex: 1
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 6
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 13.5,
          fontWeight: 600,
          color: 'var(--vb-ink)',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis'
        }
      }, c.name), /*#__PURE__*/React.createElement("span", {
        style: {
          marginLeft: 'auto',
          fontSize: 11,
          color: 'var(--vb-muted-soft)',
          flex: 'none'
        }
      }, c.time)), /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 12.5,
          color: c.unread ? 'var(--vb-body-strong)' : 'var(--vb-muted)',
          marginTop: 2,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          fontWeight: c.unread ? 500 : 400
        }
      }, c.preview), /*#__PURE__*/React.createElement("div", {
        style: {
          marginTop: 6,
          display: 'flex',
          gap: 5
        }
      }, c.assignee === 'ai' ? /*#__PURE__*/React.createElement(Badge, {
        tone: "teal"
      }, /*#__PURE__*/React.createElement(Icon, {
        name: "Bot",
        size: 11,
        color: "var(--vb-teal)",
        style: {
          marginRight: 4
        }
      }), "AI") : /*#__PURE__*/React.createElement(Badge, {
        tone: "pink",
        dot: true
      }, "Me"), c.rebuttals > 0 ? /*#__PURE__*/React.createElement(Badge, null, c.rebuttals, " rebuttals") : null)));
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        minWidth: 0,
        minHeight: 0,
        background: 'var(--vb-surface-soft)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        height: 60,
        flex: 'none',
        display: 'flex',
        alignItems: 'center',
        gap: 11,
        padding: '0 18px',
        borderBottom: '1px solid var(--vb-hairline)',
        background: 'var(--vb-canvas)'
      }
    }, /*#__PURE__*/React.createElement(Avatar, {
      name: conv.name,
      size: 34
    }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 14,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, conv.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted)',
        display: 'flex',
        alignItems: 'center',
        gap: 5
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: chIcon[conv.channel],
      size: 13,
      color: "var(--vb-muted)"
    }), " ", conv.channel, " \xB7 ", /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)'
      }
    }, conv.id.slice(0, 11)))), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement(Badge, {
      tone: stateTone[conv.state],
      dot: conv.state === 'resolved'
    }, conv.state), aiOwned ? /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "secondary",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Hand",
        size: 14,
        color: "var(--vb-ink)"
      })
    }, "Assign to me") : /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "secondary",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Bot",
        size: 14,
        color: "var(--vb-ink)"
      })
    }, "Back to AI"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Sparkles",
        size: 14,
        color: "#fff"
      })
    }, "Agent reply")), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        overflowY: 'auto',
        padding: '20px 22px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12
      }
    }, D.thread.map((m, i) => {
      const out = m.dir === 'outbound';
      const ai = m.author === 'ai';
      return /*#__PURE__*/React.createElement("div", {
        key: i,
        style: {
          display: 'flex',
          justifyContent: out ? 'flex-end' : 'flex-start'
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          maxWidth: '74%'
        }
      }, ai ? /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          justifyContent: 'flex-end',
          marginBottom: 3
        }
      }, /*#__PURE__*/React.createElement(Icon, {
        name: "Sparkles",
        size: 11,
        color: "var(--vb-teal)"
      }), /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 11,
          color: 'var(--vb-muted)',
          fontWeight: 600
        }
      }, "AI agent")) : null, /*#__PURE__*/React.createElement("div", {
        style: {
          padding: '10px 14px',
          borderRadius: 16,
          fontSize: 14,
          lineHeight: 1.5,
          background: out ? ai ? 'var(--vb-teal)' : 'var(--vb-ink)' : 'var(--vb-canvas)',
          color: out ? '#fff' : 'var(--vb-body-strong)',
          border: out ? 'none' : '1px solid var(--vb-hairline)',
          borderBottomRightRadius: out ? 4 : 16,
          borderBottomLeftRadius: out ? 16 : 4
        }
      }, m.body), /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 10.5,
          color: 'var(--vb-muted-soft)',
          marginTop: 3,
          textAlign: out ? 'right' : 'left'
        }
      }, m.time)));
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 'none',
        padding: '12px 18px',
        borderTop: '1px solid var(--vb-hairline)',
        background: 'var(--vb-canvas)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        height: 46,
        padding: '0 8px 0 16px',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-pill)'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Sparkles",
      size: 16,
      color: "var(--vb-teal)"
    }), /*#__PURE__*/React.createElement("input", {
      placeholder: "Type to reply, or let the agent answer\u2026",
      style: {
        flex: 1,
        border: 'none',
        outline: 'none',
        background: 'transparent',
        fontFamily: 'var(--font-sans)',
        fontSize: 14,
        color: 'var(--vb-ink)'
      }
    }), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Send",
        size: 14,
        color: "#fff"
      })
    }, "Send")))), /*#__PURE__*/React.createElement("div", {
      style: {
        width: 264,
        flex: 'none',
        borderLeft: '1px solid var(--vb-hairline)',
        padding: 18,
        overflowY: 'auto'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        textAlign: 'center',
        gap: 8,
        paddingBottom: 16,
        borderBottom: '1px solid var(--vb-hairline-soft)'
      }
    }, /*#__PURE__*/React.createElement(Avatar, {
      name: conv.name,
      size: 56
    }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 16,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, conv.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        color: 'var(--vb-muted)'
      }
    }, "via ", conv.channel)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: "pink",
      dot: true
    }, "Score ", conv.score), /*#__PURE__*/React.createElement(Badge, {
      tone: "success"
    }, "Consented"))), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '16px 0',
        borderBottom: '1px solid var(--vb-hairline-soft)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '1px',
        textTransform: 'uppercase',
        color: 'var(--vb-muted)',
        marginBottom: 10
      }
    }, "Why this lead is hot"), [['Visited pricing 3×', 'var(--vb-pink)'], ['Lookalike to 4 won deals', 'var(--vb-teal)'], ['Replied within 2 min', 'var(--vb-ochre)']].map(([t, c]) => /*#__PURE__*/React.createElement("div", {
      key: t,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 7
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: c,
        flex: 'none'
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        color: 'var(--vb-body)'
      }
    }, t)))), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '16px 0'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        color: 'var(--vb-body-strong)',
        fontWeight: 600
      }
    }, "Autonomous replies"), /*#__PURE__*/React.createElement(Switch, {
      defaultChecked: true,
      size: "sm"
    })), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: '8px 0 0',
        fontSize: 12,
        color: 'var(--vb-muted)',
        lineHeight: 1.5
      }
    }, "Agent answers within guardrails and escalates after ", D.harness.config.guardrails.maxRebuttals, " rebuttals."))));
  }
  window.VBInbox = Inbox;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/InboxScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/IntegrationsScreen.jsx
try { (() => {
// Appu CRM — Integrations + Agent Harness (mirrors /v1/integrations and /v1/agents/chatbot/harness).
(function () {
  const {
    Badge,
    Button
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.VBDATA;
  const provMeta = {
    whatsapp: {
      label: 'WhatsApp',
      icon: 'MessageCircle',
      color: 'var(--vb-success)'
    },
    email: {
      label: 'Email',
      icon: 'Mail',
      color: 'var(--vb-info)'
    },
    meta_leadads: {
      label: 'Meta Lead Ads',
      icon: 'Megaphone',
      color: 'var(--vb-pink)'
    },
    google_calendar: {
      label: 'Google Calendar',
      icon: 'Calendar',
      color: 'var(--vb-ochre)'
    },
    salesforce: {
      label: 'Salesforce',
      icon: 'Cloud',
      color: 'var(--vb-lavender)'
    }
  };
  function Integrations() {
    const connected = new Set(D.integrations.map(i => i.provider));
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement("section", null, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: '0 0 12px',
        fontFamily: 'var(--font-display)',
        fontSize: 17,
        fontWeight: 600,
        letterSpacing: '-0.4px',
        color: 'var(--vb-ink)'
      }
    }, "Connections"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 14
      }
    }, D.availableProviders.map(p => {
      const m = provMeta[p];
      const on = connected.has(p);
      return /*#__PURE__*/React.createElement("div", {
        key: p,
        style: {
          background: 'var(--vb-canvas)',
          border: '1px solid var(--vb-hairline)',
          borderRadius: 'var(--radius-lg)',
          padding: 18,
          display: 'flex',
          flexDirection: 'column',
          gap: 14
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 11
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          width: 40,
          height: 40,
          borderRadius: 'var(--radius-md)',
          background: 'color-mix(in oklch, ' + m.color + ' 16%, white)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center'
        }
      }, /*#__PURE__*/React.createElement(Icon, {
        name: m.icon,
        size: 20,
        color: m.color
      })), /*#__PURE__*/React.createElement("div", {
        style: {
          flex: 1
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          fontSize: 14.5,
          fontWeight: 600,
          color: 'var(--vb-ink)'
        }
      }, m.label), on ? /*#__PURE__*/React.createElement(Badge, {
        tone: "success",
        dot: true
      }, "connected") : /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 12.5,
          color: 'var(--vb-muted-soft)'
        }
      }, "not connected"))), /*#__PURE__*/React.createElement(Button, {
        fullWidth: true,
        variant: on ? 'secondary' : 'primary',
        size: "sm",
        leadingIcon: /*#__PURE__*/React.createElement(Icon, {
          name: on ? 'Settings2' : 'Plug',
          size: 14,
          color: on ? 'var(--vb-ink)' : '#fff'
        })
      }, on ? 'Manage' : 'Connect'));
    }))), /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-surface-card)',
        borderRadius: 'var(--radius-lg)',
        padding: 16,
        display: 'flex',
        alignItems: 'center',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Webhook",
      size: 18,
      color: "var(--vb-ink)"
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, "Webhook endpoint"), /*#__PURE__*/React.createElement("code", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 12.5,
        color: 'var(--vb-body)'
      }
    }, "/v1/webhooks/", D.workspace.id, "/<provider>")), /*#__PURE__*/React.createElement(Badge, null, "HMAC-verified"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "secondary",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Copy",
        size: 13,
        color: "var(--vb-ink)"
      })
    }, "Copy")));
  }
  function Harness() {
    const h = D.harness;
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 24,
        display: 'grid',
        gridTemplateColumns: '1.3fr 1fr',
        gap: 16,
        alignItems: 'start'
      }
    }, /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '14px 18px',
        borderBottom: '1px solid var(--vb-hairline)'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Bot",
      size: 18,
      color: "var(--vb-teal)"
    }), /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, "Active chatbot harness"), /*#__PURE__*/React.createElement(Badge, {
      tone: "teal",
      style: {
        marginLeft: 'auto'
      }
    }, h.config.model)), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 18,
        display: 'flex',
        flexDirection: 'column',
        gap: 14
      }
    }, /*#__PURE__*/React.createElement(Row, {
      label: "Persona",
      value: h.config.persona
    }), /*#__PURE__*/React.createElement(Row, {
      label: "Temperature",
      value: String(h.config.temperature),
      mono: true
    }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.8px',
        textTransform: 'uppercase',
        color: 'var(--vb-muted)',
        marginBottom: 8
      }
    }, "Tools"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexWrap: 'wrap',
        gap: 6
      }
    }, h.config.tools.map(t => /*#__PURE__*/React.createElement(Badge, {
      key: t,
      tone: "lavender"
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 12
      }
    }, t))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.8px',
        textTransform: 'uppercase',
        color: 'var(--vb-muted)',
        marginBottom: 8
      }
    }, "Guardrails"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexWrap: 'wrap',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: "success",
      dot: true
    }, "max ", h.config.guardrails.maxRebuttals, " rebuttals"), /*#__PURE__*/React.createElement(Badge, {
      tone: "success",
      dot: true
    }, "consent required"), /*#__PURE__*/React.createElement(Badge, {
      tone: "success",
      dot: true
    }, "never invents pricing"))))), /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '14px 18px',
        borderBottom: '1px solid var(--vb-hairline)',
        display: 'flex',
        alignItems: 'center'
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, "Versions"), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "secondary",
      style: {
        marginLeft: 'auto'
      },
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "FlaskConical",
        size: 13,
        color: "var(--vb-ink)"
      })
    }, "Run eval")), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '4px 0'
      }
    }, h.versions.map(v => /*#__PURE__*/React.createElement("div", {
      key: v.version,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '12px 18px',
        borderTop: '1px solid var(--vb-hairline-soft)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, v.version), /*#__PURE__*/React.createElement(Badge, {
      tone: v.status === 'active' ? 'teal' : 'neutral',
      dot: v.status === 'active'
    }, v.status), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement(Badge, {
      tone: v.eval ? 'success' : 'error'
    }, v.eval ? 'eval pass' : 'eval fail'))))));
  }
  function Row({
    label,
    value,
    mono
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        color: 'var(--vb-muted)'
      }
    }, label), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)'
      }
    }, value));
  }
  window.VBIntegrations = Integrations;
  window.VBHarness = Harness;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/IntegrationsScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/PipelineScreen.jsx
try { (() => {
// Appu CRM — Pipeline (stages + funnel benchmark, mirrors /v1/pipelines/funnel).
(function () {
  const {
    Badge,
    Button
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.VBDATA;
  const statusTone = {
    met: 'success',
    below: 'warning',
    above: 'neutral'
  };
  function Pipeline() {
    const p = D.pipelines[0];
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        padding: 20
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        marginBottom: 16
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Columns3",
      size: 18,
      color: "var(--vb-pink)"
    }), /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 17,
        fontWeight: 600,
        letterSpacing: '-0.4px',
        color: 'var(--vb-ink)'
      }
    }, p.name), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "secondary",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Plus",
        size: 14,
        color: "var(--vb-ink)"
      })
    }, "Add stage")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        flexWrap: 'wrap'
      }
    }, p.stages.map((s, i) => /*#__PURE__*/React.createElement(React.Fragment, {
      key: s
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 16px',
        background: i === p.stages.length - 1 ? 'var(--vb-teal)' : 'var(--vb-surface-card)',
        color: i === p.stages.length - 1 ? '#fff' : 'var(--vb-ink)',
        borderRadius: 'var(--radius-pill)',
        fontSize: 13.5,
        fontWeight: 600
      }
    }, s), i < p.stages.length - 1 ? /*#__PURE__*/React.createElement(Icon, {
      name: "ChevronRight",
      size: 16,
      color: "var(--vb-muted-soft)",
      style: {
        margin: '0 4px'
      }
    }) : null)))), /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '14px 18px',
        borderBottom: '1px solid var(--vb-hairline)'
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, "Funnel vs benchmark")), /*#__PURE__*/React.createElement("table", {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        fontFamily: 'var(--font-sans)'
      }
    }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.6px',
        textTransform: 'uppercase',
        color: 'var(--vb-muted)'
      }
    }, /*#__PURE__*/React.createElement("th", {
      style: {
        textAlign: 'left',
        padding: '10px 18px',
        fontWeight: 600
      }
    }, "Transition"), /*#__PURE__*/React.createElement("th", {
      style: {
        textAlign: 'left',
        padding: '10px 12px',
        fontWeight: 600
      }
    }, "Actual"), /*#__PURE__*/React.createElement("th", {
      style: {
        textAlign: 'left',
        padding: '10px 12px',
        fontWeight: 600
      }
    }, "Benchmark"), /*#__PURE__*/React.createElement("th", {
      style: {
        textAlign: 'left',
        padding: '10px 12px',
        fontWeight: 600
      }
    }, "Status"), /*#__PURE__*/React.createElement("th", {
      style: {
        padding: '10px 18px'
      }
    }))), /*#__PURE__*/React.createElement("tbody", null, p.funnel.map(f => /*#__PURE__*/React.createElement("tr", {
      key: f.from,
      style: {
        borderTop: '1px solid var(--vb-hairline-soft)'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '13px 18px',
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7
      }
    }, f.from, /*#__PURE__*/React.createElement(Icon, {
      name: "ArrowRight",
      size: 13,
      color: "var(--vb-muted-soft)"
    }), f.to)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '13px 12px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 80,
        height: 7,
        borderRadius: 4,
        background: 'var(--vb-hairline)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: f.actual * 100 + '%',
        height: '100%',
        background: f.status === 'below' ? 'var(--vb-warning)' : 'var(--vb-teal)'
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 12.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, Math.round(f.actual * 100), "%"))), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '13px 12px',
        fontFamily: 'var(--font-mono)',
        fontSize: 12.5,
        color: 'var(--vb-muted)'
      }
    }, Math.round(f.target * 100), "%"), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '13px 12px'
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: statusTone[f.status],
      dot: f.status === 'met'
    }, f.status)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '13px 18px',
        textAlign: 'right'
      }
    }, f.needs ? /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "secondary",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "FlaskConical",
        size: 13,
        color: "var(--vb-ink)"
      })
    }, "Suggest experiment") : null)))))));
  }
  window.VBPipeline = Pipeline;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/PipelineScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/Sidebar.jsx
try { (() => {
// Appu CRM — left navigation sidebar (real product tabs).
(function () {
  const {
    Avatar
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.VBDATA;
  const NAV = [{
    id: 'inbox',
    label: 'Inbox',
    icon: 'MessagesSquare',
    badge: 2
  }, {
    id: 'contacts',
    label: 'Contacts',
    icon: 'Users'
  }, {
    id: 'cohorts',
    label: 'Cohorts',
    icon: 'Sparkles'
  }, {
    id: 'pipeline',
    label: 'Pipeline',
    icon: 'Columns3'
  }, {
    id: 'analytics',
    label: 'Analytics',
    icon: 'ChartColumn'
  }, {
    id: 'team',
    label: 'Team',
    icon: 'UsersRound'
  }, {
    id: 'integrations',
    label: 'Integrations',
    icon: 'Plug'
  }, {
    id: 'harness',
    label: 'Agent harness',
    icon: 'Bot'
  }];
  function NavItem({
    item,
    active,
    onClick
  }) {
    const [hover, setHover] = React.useState(false);
    const on = active === item.id;
    return /*#__PURE__*/React.createElement("button", {
      onClick: () => onClick(item.id),
      onMouseEnter: () => setHover(true),
      onMouseLeave: () => setHover(false),
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 11,
        width: '100%',
        padding: '9px 12px',
        border: 'none',
        cursor: 'pointer',
        textAlign: 'left',
        borderRadius: 'var(--radius-md)',
        fontFamily: 'var(--font-sans)',
        fontSize: 14,
        fontWeight: on ? 600 : 500,
        color: on ? 'var(--vb-ink)' : 'var(--vb-muted)',
        background: on ? 'var(--vb-surface-card)' : hover ? 'var(--vb-surface-soft)' : 'transparent',
        transition: 'background 120ms ease, color 120ms ease'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: item.icon,
      size: 18,
      color: on ? 'var(--vb-ink)' : 'var(--vb-muted)',
      strokeWidth: on ? 2.2 : 2
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1
      }
    }, item.label), item.badge ? /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        fontWeight: 600,
        color: '#fff',
        background: 'var(--vb-pink)',
        borderRadius: 'var(--radius-pill)',
        padding: '1px 7px'
      }
    }, item.badge) : null);
  }
  function Sidebar({
    active,
    onNavigate
  }) {
    return /*#__PURE__*/React.createElement("aside", {
      style: {
        width: 232,
        flex: 'none',
        height: '100%',
        boxSizing: 'border-box',
        background: 'var(--vb-canvas)',
        borderRight: '1px solid var(--vb-hairline)',
        display: 'flex',
        flexDirection: 'column',
        padding: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '6px 8px 18px'
      }
    }, /*#__PURE__*/React.createElement("img", {
      src: "../../assets/vibrant-mark.svg",
      width: "26",
      height: "26",
      alt: ""
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 21,
        fontWeight: 600,
        letterSpacing: '-0.8px',
        color: 'var(--vb-ink)'
      }
    }, "Appu")), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 2
      }
    }, NAV.map(n => /*#__PURE__*/React.createElement(NavItem, {
      key: n.id,
      item: n,
      active: active,
      onClick: onNavigate
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        background: 'var(--vb-teal)',
        borderRadius: 'var(--radius-lg)',
        padding: 14,
        color: '#fff'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 7,
        marginBottom: 6
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Zap",
      size: 14,
      color: "var(--vb-ochre)"
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        fontWeight: 600,
        letterSpacing: '0.3px'
      }
    }, "Agents are working")), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 12,
        lineHeight: 1.5,
        color: 'rgba(255,255,255,0.7)'
      }
    }, "3 conversations auto-handled in the last hour.")), /*#__PURE__*/React.createElement("button", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: 8,
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--vb-canvas)',
        cursor: 'pointer',
        textAlign: 'left'
      }
    }, /*#__PURE__*/React.createElement(Avatar, {
      name: D.workspace.name,
      square: true,
      size: 30
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, D.workspace.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: 'var(--vb-muted)'
      }
    }, D.workspace.plan, " workspace")), /*#__PURE__*/React.createElement(Icon, {
      name: "ChevronsUpDown",
      size: 15,
      color: "var(--vb-muted)"
    }))));
  }
  window.VBSidebar = Sidebar;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/Sidebar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/TeamScreen.jsx
try { (() => {
// Appu CRM — Team (members + roles + invites, mirrors /v1/workspaces/members + invites).
(function () {
  const {
    Badge,
    Avatar,
    Button,
    Input
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.VBDATA;
  const inviteTone = {
    pending: 'success',
    expired: 'neutral',
    revoked: 'error'
  };
  function RolePill({
    role
  }) {
    const tone = role === 'owner' ? 'pink' : role === 'partner' ? 'teal' : role === 'admin' ? 'lavender' : 'neutral';
    return /*#__PURE__*/React.createElement(Badge, {
      tone: tone
    }, role.replace('_', ' '));
  }
  function Team() {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 24,
        display: 'grid',
        gridTemplateColumns: '1.5fr 1fr',
        gap: 16,
        alignItems: 'start'
      }
    }, /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '14px 18px',
        borderBottom: '1px solid var(--vb-hairline)'
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, "Members")), /*#__PURE__*/React.createElement("table", {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        fontFamily: 'var(--font-sans)'
      }
    }, /*#__PURE__*/React.createElement("tbody", null, D.members.map(m => /*#__PURE__*/React.createElement("tr", {
      key: m.email,
      style: {
        borderTop: '1px solid var(--vb-hairline-soft)'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 18px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 11
      }
    }, /*#__PURE__*/React.createElement(Avatar, {
      name: m.name,
      size: 34
    }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, m.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted)'
      }
    }, m.email)))), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 12px'
      }
    }, /*#__PURE__*/React.createElement(RolePill, {
      role: m.role
    })), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '12px 18px',
        textAlign: 'right',
        whiteSpace: 'nowrap'
      }
    }, /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Pencil",
        size: 13,
        color: "var(--vb-ink)"
      })
    }, "Role"), m.role !== 'owner' ? /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "UserMinus",
        size: 13,
        color: "var(--vb-error)"
      }),
      style: {
        color: 'var(--vb-error)'
      }
    }, "Remove") : null)))))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        padding: 16
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: '0 0 12px',
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, "Invite someone"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement(Input, {
      placeholder: "email@company.com",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Mail",
        size: 15,
        color: "var(--vb-muted)"
      })
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        height: 44,
        padding: '0 14px',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)',
        fontSize: 14,
        color: 'var(--vb-body)'
      }
    }, "sales agent", /*#__PURE__*/React.createElement(Icon, {
      name: "ChevronDown",
      size: 15,
      color: "var(--vb-muted)",
      style: {
        marginLeft: 'auto'
      }
    })), /*#__PURE__*/React.createElement(Button, {
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Send",
        size: 14,
        color: "#fff"
      })
    }, "Invite")))), /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '14px 18px',
        borderBottom: '1px solid var(--vb-hairline)'
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, "Invites")), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '4px 0'
      }
    }, D.invites.map(i => /*#__PURE__*/React.createElement("div", {
      key: i.email,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '11px 18px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, i.email), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted)'
      }
    }, i.role.replace('_', ' '), " \xB7 expires ", i.expires)), /*#__PURE__*/React.createElement(Badge, {
      tone: inviteTone[i.status],
      dot: i.status === 'pending'
    }, i.status), i.status === 'pending' ? /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost"
    }, "Revoke") : null))))));
  }
  window.VBTeam = Team;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/TeamScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/Topbar.jsx
try { (() => {
// Appu app — top bar with title, search, agent-autonomy toggle, user.
(function () {
  const {
    Avatar,
    Switch,
    Button
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  function Topbar({
    title,
    subtitle,
    autonomy,
    onAutonomy,
    action
  }) {
    return /*#__PURE__*/React.createElement("header", {
      style: {
        height: 64,
        flex: 'none',
        boxSizing: 'border-box',
        borderBottom: '1px solid var(--vb-hairline)',
        background: 'var(--vb-canvas)',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '0 24px'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("h1", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 19,
        fontWeight: 600,
        letterSpacing: '-0.5px',
        color: 'var(--vb-ink)',
        lineHeight: 1.1
      }
    }, title), subtitle ? /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        color: 'var(--vb-muted)',
        marginTop: 1
      }
    }, subtitle) : null), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        height: 38,
        padding: '0 12px',
        background: 'var(--vb-surface-soft)',
        borderRadius: 'var(--radius-pill)',
        width: 220
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Search",
      size: 15,
      color: "var(--vb-muted)"
    }), /*#__PURE__*/React.createElement("input", {
      placeholder: "Search contacts, deals\u2026",
      style: {
        flex: 1,
        border: 'none',
        background: 'transparent',
        outline: 'none',
        fontFamily: 'var(--font-sans)',
        fontSize: 13.5,
        color: 'var(--vb-ink)',
        minWidth: 0
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '0 4px'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        fontWeight: 600,
        color: autonomy ? 'var(--vb-ink)' : 'var(--vb-muted)'
      }
    }, "Agent autonomy"), /*#__PURE__*/React.createElement(Switch, {
      checked: autonomy,
      onChange: onAutonomy,
      size: "sm"
    })), action || /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Plus",
        size: 15,
        color: "#fff"
      })
    }, "New"), /*#__PURE__*/React.createElement(Avatar, {
      name: "Priya Nair",
      size: 34
    }));
  }
  window.VBTopbar = Topbar;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/Topbar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/data.jsx
try { (() => {
// Appu CRM — mock data mirroring the real apps/web product entities.
(function () {
  window.VBDATA = {
    workspace: {
      name: 'Acme Inc',
      id: 'ws_8f3a2c91',
      plan: 'Pro',
      role: 'owner'
    },
    user: {
      name: 'Priya Nair',
      email: 'priya@acme.com'
    },
    // ---- Inbox ----
    conversations: [{
      id: 'cv_1a2b3c4d',
      name: 'Jordan Reyes',
      channel: 'WhatsApp',
      state: 'open',
      assignee: 'ai',
      rebuttals: 2,
      score: 92,
      preview: 'Perfect, 3pm Thursday works for me!',
      time: '2m',
      unread: true
    }, {
      id: 'cv_5e6f7a8b',
      name: 'Mia Chen',
      channel: 'Email',
      state: 'human',
      assignee: 'me',
      rebuttals: 0,
      score: 88,
      preview: 'Can you share pricing for the team plan?',
      time: '11m',
      unread: true
    }, {
      id: 'cv_9c0d1e2f',
      name: 'Tomás Vidal',
      channel: 'Web',
      state: 'open',
      assignee: 'ai',
      rebuttals: 1,
      score: 74,
      preview: 'AI: Here\u2019s a 2-min overview of how\u2026',
      time: '40m',
      unread: false
    }, {
      id: 'cv_3a4b5c6d',
      name: 'Hana Suzuki',
      channel: 'WhatsApp',
      state: 'resolved',
      assignee: 'ai',
      rebuttals: 3,
      score: 61,
      preview: 'Thanks, I\u2019ll talk to my team and circle back',
      time: '3h',
      unread: false
    }],
    thread: [{
      dir: 'inbound',
      author: 'contact',
      body: 'Hi! Saw your ad — do you support WhatsApp + Salesforce sync?',
      time: '3:58pm'
    }, {
      dir: 'outbound',
      author: 'ai',
      body: 'Hey Jordan! Yes — Appu runs an omnichannel inbox across WhatsApp, web and email, and syncs two-way with Salesforce. Are you evaluating for your whole team?',
      time: '3:58pm'
    }, {
      dir: 'inbound',
      author: 'contact',
      body: 'Yes, about 12 reps. We lose a lot of inbound on weekends.',
      time: '4:01pm'
    }, {
      dir: 'outbound',
      author: 'ai',
      body: 'That\u2019s exactly the gap we close — agents qualify and book 24/7. Want me to grab 20 minutes with our team this week?',
      time: '4:01pm'
    }, {
      dir: 'inbound',
      author: 'contact',
      body: 'Perfect, 3pm Thursday works for me!',
      time: '4:03pm'
    }],
    // ---- Contacts ----
    contacts: [{
      name: 'Jordan Reyes',
      company: 'Northwind SaaS',
      status: 'qualified',
      score: 92,
      tier: 'hot',
      owner: 'Priya Nair'
    }, {
      name: 'Mia Chen',
      company: 'Lumen Health',
      status: 'qualified',
      score: 88,
      tier: 'hot',
      owner: 'Priya Nair'
    }, {
      name: 'Dev Patel',
      company: 'Brightwork',
      status: 'nurturing',
      score: 76,
      tier: 'warm',
      owner: 'Marcus Lee'
    }, {
      name: 'Tomás Vidal',
      company: 'Atlas Freight',
      status: 'new',
      score: 74,
      tier: 'warm',
      owner: null
    }, {
      name: 'Hana Suzuki',
      company: 'Kite Labs',
      status: 'nurturing',
      score: 61,
      tier: 'cool',
      owner: 'Sofia Marquez'
    }, {
      name: 'Owen Brooks',
      company: 'Verde Foods',
      status: 'new',
      score: null,
      tier: null,
      owner: null
    }],
    // ---- Cohorts ----
    cohorts: [{
      name: 'High-intent lookalikes',
      kind: 'lookalike',
      members: 214,
      color: 'pink',
      desc: 'Vector-similar to closed-won deals.'
    }, {
      name: 'Price-sensitive SaaS',
      kind: 'cluster',
      members: 486,
      color: 'lavender',
      desc: 'Compare-shopping, ROI-driven.'
    }, {
      name: 'Going cold',
      kind: 'churn',
      members: 173,
      color: 'ochre',
      desc: 'Engagement velocity dropping.'
    }, {
      name: 'Enterprise evaluators',
      kind: 'cluster',
      members: 92,
      color: 'teal',
      desc: 'Large firmographics, multi-stakeholder.'
    }],
    // ---- Pipeline ----
    pipelines: [{
      name: 'Sales pipeline',
      stages: ['Lead', 'Qualified', 'Demo', 'Proposal', 'Won'],
      funnel: [{
        from: 'Lead',
        to: 'Qualified',
        actual: 0.62,
        target: 0.55,
        status: 'met'
      }, {
        from: 'Qualified',
        to: 'Demo',
        actual: 0.41,
        target: 0.45,
        status: 'below',
        needs: true
      }, {
        from: 'Demo',
        to: 'Proposal',
        actual: 0.58,
        target: 0.50,
        status: 'met'
      }, {
        from: 'Proposal',
        to: 'Won',
        actual: 0.33,
        target: 0.35,
        status: 'below',
        needs: true
      }]
    }],
    // ---- Analytics (per-agent scorecards) ----
    agents: [{
      name: 'Priya Nair',
      role: 'owner',
      leads: 142,
      newLeads: 28,
      opps: 31,
      pipeline: 248000,
      won: 9,
      wonValue: 86000,
      lost: 4,
      winRate: 0.69,
      avgStage: 6,
      convos: 88,
      msgs: 412,
      emails: 120,
      calls: 36,
      callsConn: 22,
      meetings: 14,
      resp: 8
    }, {
      name: 'Marcus Lee',
      role: 'sales_agent',
      leads: 118,
      newLeads: 21,
      opps: 24,
      pipeline: 192000,
      won: 6,
      wonValue: 54000,
      lost: 7,
      winRate: 0.46,
      avgStage: 9,
      convos: 71,
      msgs: 318,
      emails: 96,
      calls: 41,
      callsConn: 19,
      meetings: 11,
      resp: 12
    }, {
      name: 'Sofia Marquez',
      role: 'marketer',
      leads: 96,
      newLeads: 33,
      opps: 12,
      pipeline: 88000,
      won: 3,
      wonValue: 21000,
      lost: 2,
      winRate: 0.60,
      avgStage: 7,
      convos: 44,
      msgs: 210,
      emails: 180,
      calls: 8,
      callsConn: 5,
      meetings: 6,
      resp: 18
    }],
    totals: {
      leads: 356,
      newLeads: 82,
      opps: 67,
      pipeline: 528000,
      won: 18,
      wonValue: 161000,
      lost: 13,
      msgs: 940,
      aiMessages: 318
    },
    // ---- Team ----
    members: [{
      name: 'Priya Nair',
      email: 'priya@acme.com',
      role: 'owner'
    }, {
      name: 'Marcus Lee',
      email: 'marcus@acme.com',
      role: 'sales_agent'
    }, {
      name: 'Sofia Marquez',
      email: 'sofia@acme.com',
      role: 'marketer'
    }, {
      name: 'Dev Patel',
      email: 'dev@acme.com',
      role: 'admin'
    }, {
      name: 'Aria Wells',
      email: 'aria@acme.com',
      role: 'viewer'
    }],
    invites: [{
      email: 'sam@acme.com',
      role: 'sales_agent',
      status: 'pending',
      expires: 'Jun 25'
    }, {
      email: 'lee@partner.io',
      role: 'partner',
      status: 'pending',
      expires: 'Jun 24'
    }, {
      email: 'old@acme.com',
      role: 'viewer',
      status: 'expired',
      expires: 'Jun 10'
    }],
    roles: ['owner', 'partner', 'admin', 'sales_agent', 'marketer', 'viewer'],
    // ---- Integrations ----
    integrations: [{
      provider: 'whatsapp',
      status: 'connected',
      icon: 'MessageCircle'
    }, {
      provider: 'email',
      status: 'connected',
      icon: 'Mail'
    }, {
      provider: 'meta_leadads',
      status: 'connected',
      icon: 'Megaphone'
    }, {
      provider: 'google_calendar',
      status: 'connected',
      icon: 'Calendar'
    }],
    availableProviders: ['whatsapp', 'email', 'meta_leadads', 'google_calendar', 'salesforce'],
    // ---- Harness ----
    harness: {
      config: {
        model: 'claude-sonnet-4',
        temperature: 0.4,
        persona: 'concise, warm, on-brand',
        tools: ['lookup_contact', 'answer_kb', 'qualify', 'book_meeting', 'escalate'],
        guardrails: {
          maxRebuttals: 3,
          requireConsent: true,
          neverInventPricing: true
        }
      },
      versions: [{
        version: 'v4',
        status: 'active',
        eval: true
      }, {
        version: 'v3',
        status: 'archived',
        eval: true
      }, {
        version: 'v2',
        status: 'archived',
        eval: false
      }]
    }
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/data.jsx", error: String((e && e.message) || e) }); }

// ui_kits/merchant/DashboardScreen.jsx
try { (() => {
// Appu merchant admin — Dashboard (advisor, KPIs, revenue, funnel, top products, search demand).
(function () {
  const {
    StatCard,
    Badge,
    Button,
    Tabs
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.MDATA;
  const sevMeta = {
    critical: {
      tone: 'error',
      icon: 'CircleAlert',
      color: 'var(--vb-error)'
    },
    warning: {
      tone: 'warning',
      icon: 'TriangleAlert',
      color: 'var(--vb-warning)'
    },
    opportunity: {
      tone: 'lavender',
      icon: 'Lightbulb',
      color: 'var(--vb-lavender)'
    }
  };
  const gradeTint = {
    A: 'var(--vb-success)',
    B: 'var(--vb-teal)',
    C: 'var(--vb-ochre)',
    D: 'var(--vb-error)'
  };
  function Panel({
    title,
    subtitle,
    action,
    children,
    style
  }) {
    return /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
        ...style
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '14px 18px',
        borderBottom: '1px solid var(--vb-hairline-soft)'
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 15.5,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, title), subtitle ? /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted)',
        marginTop: 1
      }
    }, subtitle) : null), /*#__PURE__*/React.createElement("div", {
      style: {
        marginLeft: 'auto'
      }
    }, action)), children);
  }
  function Dashboard() {
    const max = Math.max(...D.revenue);
    const fmax = Math.max(...D.funnel.map(f => f.count));
    const vals = {
      rev: D.money(D.summary.revenueMinor),
      orders: D.summary.paidOrders,
      aov: D.money(D.summary.aovMinor),
      cust: D.summary.newCustomers
    };
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 22,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement(Panel, {
      title: "Store health & next best actions",
      subtitle: D.advisor.summary,
      action: /*#__PURE__*/React.createElement("span", {
        style: {
          width: 34,
          height: 34,
          borderRadius: 'var(--radius-md)',
          background: 'color-mix(in oklch, ' + gradeTint[D.advisor.grade] + ' 16%, white)',
          color: gradeTint[D.advisor.grade],
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'var(--font-display)',
          fontSize: 16,
          fontWeight: 700
        }
      }, D.advisor.grade)
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 16,
        padding: '8px 18px',
        fontSize: 12,
        color: 'var(--vb-muted)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Activity",
      size: 13,
      color: "var(--vb-muted)"
    }), "Health ", D.advisor.score, "/100 \xB7 readiness ", D.advisor.readiness, "%"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-error)'
      }
    }, D.advisor.counts.critical, " critical"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#8a5a06'
      }
    }, D.advisor.counts.warning, " warning"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: '#5b4a8a'
      }
    }, D.advisor.counts.opportunity, " opportunity")), /*#__PURE__*/React.createElement("div", null, D.advisor.recs.map((r, i) => {
      const m = sevMeta[r.sev];
      return /*#__PURE__*/React.createElement("div", {
        key: i,
        style: {
          display: 'flex',
          alignItems: 'flex-start',
          gap: 11,
          padding: '11px 18px',
          borderTop: '1px solid var(--vb-hairline-soft)'
        }
      }, /*#__PURE__*/React.createElement(Icon, {
        name: m.icon,
        size: 17,
        color: m.color,
        style: {
          marginTop: 1,
          flex: 'none'
        }
      }), /*#__PURE__*/React.createElement("div", {
        style: {
          flex: 1,
          minWidth: 0
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: 8
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          fontSize: 13.5,
          fontWeight: 600,
          color: 'var(--vb-ink)'
        }
      }, r.title), /*#__PURE__*/React.createElement(Badge, {
        tone: m.tone
      }, r.sev)), /*#__PURE__*/React.createElement("p", {
        style: {
          margin: '2px 0 0',
          fontSize: 12.5,
          color: 'var(--vb-muted)',
          lineHeight: 1.45
        }
      }, r.detail)), /*#__PURE__*/React.createElement(Button, {
        size: "sm",
        variant: "secondary",
        trailingIcon: /*#__PURE__*/React.createElement(Icon, {
          name: "ArrowRight",
          size: 13,
          color: "var(--vb-ink)"
        })
      }, r.action));
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 14
      }
    }, D.stats.map(s => /*#__PURE__*/React.createElement(StatCard, {
      key: s.key,
      label: s.label,
      value: vals[s.key],
      delta: s.delta,
      deltaDir: s.up ? 'up' : 'down',
      icon: /*#__PURE__*/React.createElement(Icon, {
        name: s.icon,
        size: 16,
        color: "#fff"
      }),
      accent: s.accent
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: '1.5fr 1fr',
        gap: 14,
        alignItems: 'start'
      }
    }, /*#__PURE__*/React.createElement(Panel, {
      title: "Revenue",
      subtitle: "Paid orders \xB7 weekly"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 18
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'flex-end',
        gap: 10,
        height: 180
      }
    }, D.revenue.map((v, i) => /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: '100%',
        maxWidth: 34,
        height: v / max * 150,
        background: 'linear-gradient(180deg, var(--vb-pink), color-mix(in oklch, var(--vb-pink) 55%, white))',
        borderRadius: '5px 5px 0 0'
      },
      title: '₹' + v + 'k'
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 10.5,
        color: 'var(--vb-muted-soft)',
        fontFamily: 'var(--font-mono)'
      }
    }, "W", i + 1)))))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 14
      }
    }, /*#__PURE__*/React.createElement(Panel, {
      title: "Conversion funnel",
      subtitle: "Cart \u2192 checkout \u2192 paid"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 18,
        display: 'flex',
        flexDirection: 'column',
        gap: 12
      }
    }, D.funnel.map((f, i) => /*#__PURE__*/React.createElement("div", {
      key: f.stage
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: 12.5,
        marginBottom: 4
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-body)',
        fontWeight: 500
      }
    }, f.stage), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        color: 'var(--vb-ink)',
        fontWeight: 600
      }
    }, f.count.toLocaleString('en-IN'))), /*#__PURE__*/React.createElement("div", {
      style: {
        height: 8,
        borderRadius: 5,
        background: 'var(--vb-hairline)',
        overflow: 'hidden'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: f.count / fmax * 100 + '%',
        height: '100%',
        background: ['var(--vb-lavender)', 'var(--vb-ochre)', 'var(--vb-teal)'][i]
      }
    })))))), /*#__PURE__*/React.createElement(Panel, {
      title: "Top products",
      subtitle: "By revenue"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '6px 0'
      }
    }, D.topProducts.map(p => /*#__PURE__*/React.createElement("div", {
      key: p.title,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 18px',
        fontSize: 13
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, p.title), /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-muted)'
      }
    }, p.units, " sold"), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontWeight: 600,
        color: 'var(--vb-ink)',
        minWidth: 60,
        textAlign: 'right'
      }
    }, D.money(p.rev)))))))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 14
      }
    }, /*#__PURE__*/React.createElement(Panel, {
      title: "Top searches",
      subtitle: "On-site search this period"
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '6px 0'
      }
    }, D.topSearches.map(([q, n]) => /*#__PURE__*/React.createElement("div", {
      key: q,
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        padding: '8px 18px',
        fontSize: 13
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontWeight: 500,
        color: 'var(--vb-ink)'
      }
    }, q), /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-muted)'
      }
    }, n, "\xD7"))))), /*#__PURE__*/React.createElement(Panel, {
      title: "Unmet demand",
      subtitle: "Searched for \u2014 but you don't stock it",
      action: /*#__PURE__*/React.createElement(Badge, {
        tone: "warning"
      }, D.unmet.length)
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        padding: '6px 0'
      }
    }, D.unmet.map(([q, n]) => /*#__PURE__*/React.createElement("div", {
      key: q,
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '8px 18px',
        fontSize: 13
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontWeight: 500,
        color: 'var(--vb-ink)'
      }
    }, q), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted)'
      }
    }, n, " found nothing")))))));
  }
  window.MDashboard = Dashboard;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/merchant/DashboardScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/merchant/MerchantNav.jsx
try { (() => {
// Appu merchant admin — sidebar (real product nav, grouped) + topbar store switcher.
(function () {
  const Icon = window.Icon;
  const D = window.MDATA;
  const GROUPS = [{
    title: null,
    items: [['dashboard', 'Dashboard', 'LayoutDashboard'], ['stores', 'Stores', 'Store']]
  }, {
    title: 'Catalog',
    items: [['products', 'Products', 'Package'], ['quicklist', 'Quick List', 'Wand2'], ['pricing', 'Pricing', 'TrendingDown'], ['bundles', 'Bundles', 'Boxes'], ['discounts', 'Discounts', 'Tag'], ['reviews', 'Reviews', 'Star'], ['stock', 'Stock', 'Activity'], ['design', 'Design', 'Palette'], ['seo', 'SEO & Speed', 'Search']]
  }, {
    title: 'Sales',
    items: [['orders', 'Orders', 'ShoppingCart'], ['carts', 'Carts', 'ShoppingBasket'], ['shipments', 'Shipments', 'Truck'], ['returns', 'Returns', 'Undo2'], ['invoicing', 'Invoicing', 'FileText']]
  }, {
    title: 'Customers',
    items: [['customers', 'Customers', 'Users'], ['cohorts', 'Cohorts', 'Sparkles'], ['loyalty', 'Loyalty', 'Gift'], ['subscriptions', 'Subscriptions', 'Repeat'], ['marketing', 'Marketing', 'Megaphone'], ['automation', 'Automation', 'Send']]
  }, {
    title: 'Setup',
    items: [['integrations', 'Integrations', 'Plug'], ['apps', 'Apps', 'Puzzle'], ['notifications', 'Notifications', 'Bell'], ['support', 'Support', 'MessageSquare'], ['team', 'Team', 'UserCog'], ['settings', 'Settings', 'Settings']]
  }];
  function Item({
    id,
    label,
    icon,
    active,
    onNav
  }) {
    const [h, setH] = React.useState(false);
    const on = active === id;
    return /*#__PURE__*/React.createElement("button", {
      onClick: () => onNav(id),
      onMouseEnter: () => setH(true),
      onMouseLeave: () => setH(false),
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        width: '100%',
        padding: '7px 11px',
        border: 'none',
        cursor: 'pointer',
        textAlign: 'left',
        borderRadius: 'var(--radius-md)',
        fontFamily: 'var(--font-sans)',
        fontSize: 13.5,
        fontWeight: on ? 600 : 500,
        color: on ? 'var(--vb-ink)' : 'var(--vb-muted)',
        background: on ? 'var(--vb-surface-card)' : h ? 'var(--vb-surface-soft)' : 'transparent',
        transition: 'background 120ms'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: icon,
      size: 16,
      color: on ? 'var(--vb-ink)' : 'var(--vb-muted)',
      strokeWidth: on ? 2.2 : 2
    }), label);
  }
  function MerchantNav({
    active,
    onNav
  }) {
    return /*#__PURE__*/React.createElement("aside", {
      style: {
        width: 224,
        flex: 'none',
        height: '100%',
        boxSizing: 'border-box',
        background: 'var(--vb-canvas)',
        borderRight: '1px solid var(--vb-hairline)',
        display: 'flex',
        flexDirection: 'column'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        padding: '16px 16px 12px',
        flex: 'none'
      }
    }, /*#__PURE__*/React.createElement("img", {
      src: "../../assets/vibrant-mark.svg",
      width: "24",
      height: "24",
      alt: ""
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 19,
        fontWeight: 600,
        letterSpacing: '-0.6px',
        color: 'var(--vb-ink)'
      }
    }, "Appu"), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        fontWeight: 600,
        color: 'var(--vb-muted)',
        background: 'var(--vb-surface-card)',
        padding: '2px 7px',
        borderRadius: 'var(--radius-pill)',
        marginLeft: 'auto'
      }
    }, "Merchant")), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        overflowY: 'auto',
        padding: '0 12px 12px'
      }
    }, GROUPS.map((g, gi) => /*#__PURE__*/React.createElement("div", {
      key: gi,
      style: {
        marginTop: gi ? 14 : 0
      }
    }, g.title ? /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 10.5,
        fontWeight: 600,
        letterSpacing: '0.8px',
        textTransform: 'uppercase',
        color: 'var(--vb-muted-soft)',
        padding: '0 11px 6px'
      }
    }, g.title) : null, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 1
      }
    }, g.items.map(([id, label, icon]) => /*#__PURE__*/React.createElement(Item, {
      key: id,
      id: id,
      label: label,
      icon: icon,
      active: active,
      onNav: onNav
    })))))), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 'none',
        borderTop: '1px solid var(--vb-hairline)',
        padding: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 9
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 30,
        height: 30,
        borderRadius: '50%',
        background: 'var(--vb-teal)',
        color: '#fff',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 12,
        fontWeight: 600
      }
    }, "PN"), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
      }
    }, D.me.email), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11,
        color: 'var(--vb-muted)'
      }
    }, D.me.role)), /*#__PURE__*/React.createElement(Icon, {
      name: "LogOut",
      size: 15,
      color: "var(--vb-muted)",
      style: {
        cursor: 'pointer'
      }
    })));
  }
  function MerchantTopbar({
    title,
    store,
    onStore
  }) {
    return /*#__PURE__*/React.createElement("header", {
      style: {
        height: 56,
        flex: 'none',
        borderBottom: '1px solid var(--vb-hairline)',
        background: 'var(--vb-canvas)',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '0 22px'
      }
    }, /*#__PURE__*/React.createElement("h1", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 17,
        fontWeight: 600,
        letterSpacing: '-0.4px',
        color: 'var(--vb-ink)'
      }
    }, title), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12.5,
        color: 'var(--vb-muted)'
      }
    }, "Active store"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        height: 36,
        padding: '0 12px',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--vb-canvas)',
        cursor: 'pointer'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, store.name), /*#__PURE__*/React.createElement(Icon, {
      name: "ChevronsUpDown",
      size: 14,
      color: "var(--vb-muted)"
    })));
  }
  window.MSidebar = MerchantNav;
  window.MTopbar = MerchantTopbar;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/merchant/MerchantNav.jsx", error: String((e && e.message) || e) }); }

// ui_kits/merchant/Screens.jsx
try { (() => {
// Appu merchant admin — Orders, Products, Customers screens.
(function () {
  const {
    Badge,
    Button,
    Avatar
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const D = window.MDATA;
  const th = extra => ({
    textAlign: 'left',
    padding: '10px 18px',
    fontWeight: 600,
    fontSize: 11,
    letterSpacing: '0.5px',
    textTransform: 'uppercase',
    color: 'var(--vb-muted)',
    ...extra
  });
  const td = extra => ({
    padding: '12px 18px',
    fontSize: 13.5,
    color: 'var(--vb-body)',
    borderTop: '1px solid var(--vb-hairline-soft)',
    ...extra
  });
  function TablePanel({
    title,
    subtitle,
    action,
    children
  }) {
    return /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden'
      }
    }, title ? /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '14px 18px',
        borderBottom: '1px solid var(--vb-hairline)'
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
      style: {
        margin: 0,
        fontFamily: 'var(--font-display)',
        fontSize: 15.5,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, title), subtitle ? /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted)',
        marginTop: 1
      }
    }, subtitle) : null), /*#__PURE__*/React.createElement("div", {
      style: {
        marginLeft: 'auto'
      }
    }, action)) : null, children);
  }

  // ---------- Orders ----------
  const statusTone = {
    PENDING: 'warning',
    PAID: 'success',
    FULFILLED: 'teal',
    CANCELLED: 'neutral',
    REFUNDED: 'error'
  };
  const payTone = {
    CAPTURED: 'success',
    PENDING: 'warning',
    REFUNDED: 'neutral',
    FAILED: 'error'
  };
  function Orders() {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 22,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement("section", {
      style: {
        background: 'var(--vb-surface-card)',
        borderRadius: 'var(--radius-lg)',
        padding: '14px 18px',
        display: 'flex',
        alignItems: 'center',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Receipt",
      size: 17,
      color: "var(--vb-ink)"
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, "Checkout \xB7 tax & shipping"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted)'
      }
    }, "18% GST \xB7 \u20B950 shipping \xB7 free over \u20B9499 \xB7 address required")), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "secondary"
    }, "Edit")), /*#__PURE__*/React.createElement(TablePanel, {
      title: "Orders",
      subtitle: D.stores[0].name + ' · ' + D.orders.length + ' recent'
    }, /*#__PURE__*/React.createElement("table", {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        fontFamily: 'var(--font-sans)'
      }
    }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Order"), /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Customer"), /*#__PURE__*/React.createElement("th", {
      style: th({
        textAlign: 'right'
      })
    }, "Items"), /*#__PURE__*/React.createElement("th", {
      style: th({
        textAlign: 'right'
      })
    }, "Total"), /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Payment"), /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Status"))), /*#__PURE__*/React.createElement("tbody", null, D.orders.map(o => /*#__PURE__*/React.createElement("tr", {
      key: o.number
    }, /*#__PURE__*/React.createElement("td", {
      style: td({
        fontFamily: 'var(--font-mono)',
        fontWeight: 600,
        color: 'var(--vb-ink)'
      })
    }, "#", o.number), /*#__PURE__*/React.createElement("td", {
      style: td()
    }, o.customer), /*#__PURE__*/React.createElement("td", {
      style: td({
        textAlign: 'right'
      })
    }, o.items), /*#__PURE__*/React.createElement("td", {
      style: td({
        textAlign: 'right',
        fontFamily: 'var(--font-mono)',
        fontWeight: 600,
        color: 'var(--vb-ink)'
      })
    }, D.money(o.totalMinor)), /*#__PURE__*/React.createElement("td", {
      style: td()
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: payTone[o.payment]
    }, o.payment)), /*#__PURE__*/React.createElement("td", {
      style: td()
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
        padding: '5px 10px',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-sm)',
        background: 'var(--vb-canvas)',
        cursor: 'pointer'
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: statusTone[o.status],
      dot: o.status === 'PAID' || o.status === 'FULFILLED'
    }, o.status), /*#__PURE__*/React.createElement(Icon, {
      name: "ChevronDown",
      size: 13,
      color: "var(--vb-muted)"
    })))))))));
  }

  // ---------- Products ----------
  const stockColor = {
    green: 'var(--vb-success)',
    amber: 'var(--vb-warning)',
    red: 'var(--vb-error)'
  };
  const prodStatusTone = {
    ACTIVE: 'success',
    DRAFT: 'neutral',
    ARCHIVED: 'neutral'
  };
  function Products() {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 22,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement(TablePanel, {
      title: "Products",
      subtitle: D.stores[0].name + ' · ' + D.products.length + ' products',
      action: /*#__PURE__*/React.createElement(Button, {
        size: "sm",
        leadingIcon: /*#__PURE__*/React.createElement(Icon, {
          name: "Plus",
          size: 14,
          color: "#fff"
        })
      }, "New product")
    }, /*#__PURE__*/React.createElement("table", {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        fontFamily: 'var(--font-sans)'
      }
    }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Product"), /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Status"), /*#__PURE__*/React.createElement("th", {
      style: th({
        textAlign: 'right'
      })
    }, "Price"), /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "SKU"), /*#__PURE__*/React.createElement("th", {
      style: th({
        textAlign: 'right'
      })
    }, "Inventory"), /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Stock"))), /*#__PURE__*/React.createElement("tbody", null, D.products.map(p => /*#__PURE__*/React.createElement("tr", {
      key: p.sku
    }, /*#__PURE__*/React.createElement("td", {
      style: td()
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 11
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 36,
        height: 36,
        borderRadius: 'var(--radius-sm)',
        background: 'var(--vb-surface-card)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flex: 'none'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Leaf",
      size: 16,
      color: "var(--vb-teal)"
    })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, p.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted-soft)'
      }
    }, p.desc)))), /*#__PURE__*/React.createElement("td", {
      style: td()
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: prodStatusTone[p.status],
      dot: p.status === 'ACTIVE'
    }, p.status)), /*#__PURE__*/React.createElement("td", {
      style: td({
        textAlign: 'right'
      })
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, D.money(p.priceMinor)), p.compareAt ? /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 6,
        fontSize: 12,
        color: 'var(--vb-muted-soft)',
        textDecoration: 'line-through'
      }
    }, D.money(p.compareAt)) : null), /*#__PURE__*/React.createElement("td", {
      style: td({
        fontFamily: 'var(--font-mono)',
        fontSize: 12.5,
        color: 'var(--vb-muted)'
      })
    }, p.sku), /*#__PURE__*/React.createElement("td", {
      style: td({
        textAlign: 'right'
      })
    }, p.inv), /*#__PURE__*/React.createElement("td", {
      style: td()
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 9,
        height: 9,
        borderRadius: '50%',
        background: stockColor[p.stock],
        flex: 'none'
      }
    }), /*#__PURE__*/React.createElement("button", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        fontSize: 12.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Sliders",
      size: 13,
      color: "var(--vb-ink)"
    }), "Merchandise")))))))));
  }

  // ---------- Customers ----------
  const segTone = {
    VIP: 'pink',
    REPEAT: 'teal',
    NEW: 'lavender',
    AT_RISK: 'warning',
    LAPSED: 'neutral',
    ONE_TIME: 'success'
  };
  function Customers() {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 22,
        display: 'flex',
        flexDirection: 'column',
        gap: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(6, 1fr)',
        gap: 12
      }
    }, D.segments.map(s => /*#__PURE__*/React.createElement("div", {
      key: s.id,
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)',
        padding: 14
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 24,
        fontWeight: 600,
        letterSpacing: '-0.8px',
        color: 'var(--vb-ink)'
      }
    }, s.count), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 4
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: segTone[s.id],
      dot: true
    }, s.id.replace('_', ' ')))))), /*#__PURE__*/React.createElement(TablePanel, {
      title: "Customers",
      subtitle: "360\xB0 profiles \xB7 RFM segments, LTV & loyalty",
      action: /*#__PURE__*/React.createElement(Button, {
        size: "sm",
        variant: "secondary",
        leadingIcon: /*#__PURE__*/React.createElement(Icon, {
          name: "Download",
          size: 14,
          color: "var(--vb-ink)"
        })
      }, "Export")
    }, /*#__PURE__*/React.createElement("table", {
      style: {
        width: '100%',
        borderCollapse: 'collapse',
        fontFamily: 'var(--font-sans)'
      }
    }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Customer"), /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Segment"), /*#__PURE__*/React.createElement("th", {
      style: th({
        textAlign: 'right'
      })
    }, "LTV"), /*#__PURE__*/React.createElement("th", {
      style: th({
        textAlign: 'right'
      })
    }, "Orders"), /*#__PURE__*/React.createElement("th", {
      style: th({
        textAlign: 'right'
      })
    }, "AOV"), /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Tier"), /*#__PURE__*/React.createElement("th", {
      style: th()
    }, "Tags"))), /*#__PURE__*/React.createElement("tbody", null, D.customers.map(c => /*#__PURE__*/React.createElement("tr", {
      key: c.email
    }, /*#__PURE__*/React.createElement("td", {
      style: td()
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement(Avatar, {
      name: c.name,
      size: 32
    }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, c.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted-soft)'
      }
    }, c.email)))), /*#__PURE__*/React.createElement("td", {
      style: td()
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: segTone[c.segment],
      dot: c.segment === 'VIP'
    }, c.segment.replace('_', ' '))), /*#__PURE__*/React.createElement("td", {
      style: td({
        textAlign: 'right',
        fontFamily: 'var(--font-mono)',
        fontWeight: 600,
        color: 'var(--vb-ink)'
      })
    }, D.money(c.ltv)), /*#__PURE__*/React.createElement("td", {
      style: td({
        textAlign: 'right'
      })
    }, c.orders), /*#__PURE__*/React.createElement("td", {
      style: td({
        textAlign: 'right',
        fontFamily: 'var(--font-mono)',
        color: 'var(--vb-muted)'
      })
    }, c.aov ? D.money(c.aov) : '—'), /*#__PURE__*/React.createElement("td", {
      style: td()
    }, c.tier === '—' ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-muted-soft)'
      }
    }, "\u2014") : /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Crown",
      size: 13,
      color: "var(--vb-ochre)"
    }), c.tier)), /*#__PURE__*/React.createElement("td", {
      style: td()
    }, c.tags.length ? c.tags.map(t => /*#__PURE__*/React.createElement(Badge, {
      key: t,
      style: {
        marginRight: 4
      }
    }, t)) : /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-muted-soft)'
      }
    }, "\u2014"))))))));
  }
  window.MOrders = Orders;
  window.MProducts = Products;
  window.MCustomers = Customers;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/merchant/Screens.jsx", error: String((e && e.message) || e) }); }

// ui_kits/merchant/data.jsx
try { (() => {
// Appu merchant admin — mock data mirroring the real frontend/ entities (₹/INR).
(function () {
  const money = paise => '₹' + Math.round((paise || 0) / 100).toLocaleString('en-IN');
  window.MDATA = {
    money,
    stores: [{
      id: 's1',
      name: 'Saanjh'
    }, {
      id: 's2',
      name: 'Verde Foods'
    }],
    me: {
      email: 'priya@saanjh.in',
      role: 'OWNER'
    },
    summary: {
      revenueMinor: 84720000,
      paidOrders: 412,
      aovMinor: 205600,
      newCustomers: 168
    },
    stats: [{
      label: 'Revenue (paid)',
      key: 'rev',
      icon: 'IndianRupee',
      accent: 'var(--vb-ochre)',
      delta: '+12%',
      up: true
    }, {
      label: 'Paid orders',
      key: 'orders',
      icon: 'CircleCheck',
      accent: 'var(--vb-teal)',
      delta: '+8%',
      up: true
    }, {
      label: 'Avg order value',
      key: 'aov',
      icon: 'TrendingUp',
      accent: 'var(--vb-lavender)',
      delta: '+3%',
      up: true
    }, {
      label: 'New customers',
      key: 'cust',
      icon: 'Users',
      accent: 'var(--vb-pink)',
      delta: '+21%',
      up: true
    }],
    revenue: [62, 71, 58, 84, 92, 78, 103, 96],
    // ₹k per bucket
    funnel: [{
      stage: 'Cart',
      count: 1840
    }, {
      stage: 'Checkout',
      count: 720
    }, {
      stage: 'Paid',
      count: 412
    }],
    topProducts: [{
      title: 'Masala Chai',
      units: 312,
      rev: 10888800
    }, {
      title: 'Cardamom Chai',
      units: 241,
      rev: 8892900
    }, {
      title: 'Kashmiri Kahwa',
      units: 128,
      rev: 6144000
    }, {
      title: 'Darjeeling First Flush',
      units: 96,
      rev: 5184000
    }],
    advisor: {
      grade: 'B',
      score: 78,
      readiness: 92,
      summary: 'Healthy store — a few quick wins to lift conversion.',
      counts: {
        critical: 1,
        warning: 2,
        opportunity: 3
      },
      recs: [{
        sev: 'critical',
        title: 'Low stock on a bestseller',
        detail: 'Masala Chai 250g is below reorder point — restock to avoid losing sales.',
        action: 'Restock'
      }, {
        sev: 'warning',
        title: 'Cart → checkout drop-off',
        detail: '61% of carts never reach checkout. Try a saved-cart reminder.',
        action: 'Set up'
      }, {
        sev: 'warning',
        title: '3 products missing alt text',
        detail: 'Add alt text so they rank and pass accessibility checks.',
        action: 'Fix SEO'
      }, {
        sev: 'opportunity',
        title: 'Unmet search demand: “oolong”',
        detail: '24 shoppers searched “oolong” and found nothing. Consider stocking it.',
        action: 'Add product'
      }, {
        sev: 'opportunity',
        title: 'Bundle suggestion',
        detail: 'Masala Chai + Cardamom Chai are bought together 40% of the time.',
        action: 'Make bundle'
      }, {
        sev: 'opportunity',
        title: 'Win back 38 lapsed customers',
        detail: 'A re-engagement journey could recover ₹62k of LTV.',
        action: 'Launch'
      }]
    },
    topSearches: [['masala chai', 184], ['green tea', 96], ['gift box', 71], ['oolong', 24], ['kahwa', 19]],
    unmet: [['oolong', 24], ['white tea', 11], ['matcha', 7]],
    orders: [{
      number: 1042,
      customer: 'Ananya Rao',
      items: 3,
      totalMinor: 109800,
      payment: 'CAPTURED',
      status: 'PAID'
    }, {
      number: 1041,
      customer: 'Vikram Shah',
      items: 1,
      totalMinor: 54000,
      payment: 'CAPTURED',
      status: 'FULFILLED'
    }, {
      number: 1040,
      customer: 'Meera Iyer',
      items: 2,
      totalMinor: 71800,
      payment: 'PENDING',
      status: 'PENDING'
    }, {
      number: 1039,
      customer: 'Rohan Das',
      items: 5,
      totalMinor: 184500,
      payment: 'CAPTURED',
      status: 'PAID'
    }, {
      number: 1038,
      customer: 'Sara Khan',
      items: 1,
      totalMinor: 27500,
      payment: 'REFUNDED',
      status: 'REFUNDED'
    }, {
      number: 1037,
      customer: 'Arjun Nair',
      items: 2,
      totalMinor: 96900,
      payment: 'FAILED',
      status: 'CANCELLED'
    }],
    orderStatuses: ['PENDING', 'PAID', 'FULFILLED', 'CANCELLED', 'REFUNDED'],
    products: [{
      title: 'Masala Chai',
      desc: 'Bold Assam CTC + whole spices',
      status: 'ACTIVE',
      priceMinor: 34900,
      compareAt: 42000,
      sku: 'CHAI-MAS',
      inv: 8,
      stock: 'red'
    }, {
      title: 'Cardamom Chai',
      desc: 'Single-spice green cardamom',
      status: 'ACTIVE',
      priceMinor: 36900,
      sku: 'CHAI-CAR',
      inv: 64,
      stock: 'green'
    }, {
      title: 'Kashmiri Kahwa',
      desc: 'Saffron, almond & spice',
      status: 'ACTIVE',
      priceMinor: 48000,
      compareAt: 56000,
      sku: 'TEA-KAH',
      inv: 22,
      stock: 'amber'
    }, {
      title: 'Darjeeling First Flush',
      desc: 'Bright, floral spring pluck',
      status: 'ACTIVE',
      priceMinor: 54000,
      sku: 'TEA-DAR',
      inv: 47,
      stock: 'green'
    }, {
      title: 'Tulsi Green',
      desc: 'Holy basil + green tea',
      status: 'DRAFT',
      priceMinor: 29900,
      sku: 'TEA-TUL',
      inv: 0,
      stock: 'red'
    }],
    segments: [{
      id: 'VIP',
      count: 84,
      color: 'pink'
    }, {
      id: 'REPEAT',
      count: 312,
      color: 'teal'
    }, {
      id: 'NEW',
      count: 168,
      color: 'lavender'
    }, {
      id: 'AT_RISK',
      count: 56,
      color: 'ochre'
    }, {
      id: 'LAPSED',
      count: 38,
      color: 'peach'
    }, {
      id: 'ONE_TIME',
      count: 204,
      color: 'mint'
    }],
    customers: [{
      name: 'Ananya Rao',
      email: 'ananya@example.in',
      ltv: 1840000,
      orders: 12,
      aov: 153300,
      tier: 'Gold',
      segment: 'VIP',
      tags: ['wholesale']
    }, {
      name: 'Vikram Shah',
      email: 'vikram@example.in',
      ltv: 624000,
      orders: 5,
      aov: 124800,
      tier: 'Silver',
      segment: 'REPEAT',
      tags: []
    }, {
      name: 'Meera Iyer',
      email: 'meera@example.in',
      ltv: 71800,
      orders: 1,
      aov: 71800,
      tier: 'Bronze',
      segment: 'NEW',
      tags: ['gifting']
    }, {
      name: 'Rohan Das',
      email: 'rohan@example.in',
      ltv: 988000,
      orders: 7,
      aov: 141100,
      tier: 'Gold',
      segment: 'VIP',
      tags: []
    }, {
      name: 'Sara Khan',
      email: 'sara@example.in',
      ltv: 27500,
      orders: 1,
      aov: 27500,
      tier: 'Bronze',
      segment: 'AT_RISK',
      tags: []
    }, {
      name: 'Arjun Nair',
      email: 'arjun@example.in',
      ltv: 0,
      orders: 0,
      aov: 0,
      tier: '—',
      segment: 'LAPSED',
      tags: ['refunded']
    }]
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/merchant/data.jsx", error: String((e && e.message) || e) }); }

// ui_kits/storefront/CartScreen.jsx
try { (() => {
// Appu storefront — Cart & checkout (line items, summary, India address, rewards, coupon).
(function () {
  const {
    Button,
    Badge,
    Input,
    Switch
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const S = window.SHOP;
  function CartRow({
    label,
    value,
    muted
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: 14
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-muted)'
      }
    }, label), /*#__PURE__*/React.createElement("span", {
      style: {
        color: muted ? 'var(--vb-muted)' : 'var(--vb-body-strong)',
        fontWeight: muted ? 400 : 500
      }
    }, value));
  }
  function Cart({
    onNav,
    items,
    setItems
  }) {
    const [redeem, setRedeem] = React.useState(false);
    const [code, setCode] = React.useState('');
    const [applied, setApplied] = React.useState(false);
    const subtotal = items.reduce((s, i) => s + i.price * i.qty, 0);
    const discount = applied ? Math.round(subtotal * 0.1) : 0;
    const pointsValue = redeem ? S.rewards.points * 100 : 0; // 1 pt = ₹1
    const shipping = subtotal >= 49900 ? 0 : 5000;
    const tax = Math.round((subtotal - discount) * 0.05);
    const total = Math.max(0, subtotal - discount - pointsValue + shipping + tax);
    const setQty = (idx, q) => setItems(items.map((it, i) => i === idx ? {
      ...it,
      qty: Math.max(1, q)
    } : it));
    const remove = idx => setItems(items.filter((_, i) => i !== idx));
    const crossSell = S.products.filter(p => !items.some(i => i.id === p.id) && p.avail !== 'out_of_stock').slice(0, 4);
    if (!items.length) {
      return /*#__PURE__*/React.createElement("div", {
        style: {
          maxWidth: 760,
          margin: '40px auto',
          textAlign: 'center'
        }
      }, /*#__PURE__*/React.createElement(Icon, {
        name: "ShoppingCart",
        size: 40,
        color: "var(--vb-muted-soft)",
        style: {
          margin: '0 auto 12px'
        }
      }), /*#__PURE__*/React.createElement("p", {
        style: {
          fontSize: 16,
          color: 'var(--vb-muted)'
        }
      }, "Your cart is empty."), /*#__PURE__*/React.createElement(Button, {
        onClick: () => onNav('home'),
        leadingIcon: /*#__PURE__*/React.createElement(Icon, {
          name: "ArrowLeft",
          size: 15,
          color: "#fff"
        })
      }, "Browse teas"));
    }
    return /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: 880,
        margin: '0 auto',
        display: 'grid',
        gridTemplateColumns: '1.5fr 1fr',
        gap: 20,
        alignItems: 'start'
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h1", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 26,
        fontWeight: 600,
        letterSpacing: '-0.7px',
        color: 'var(--vb-ink)',
        margin: '0 0 14px'
      }
    }, "Your cart"), /*#__PURE__*/React.createElement("div", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden'
      }
    }, items.map((i, idx) => /*#__PURE__*/React.createElement("div", {
      key: i.id,
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: 16,
        borderBottom: idx < items.length - 1 ? '1px solid var(--vb-hairline-soft)' : 'none'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 60,
        height: 60,
        borderRadius: 'var(--radius-md)',
        background: S.tint(i.img),
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flex: 'none'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Leaf",
      size: 24,
      color: "rgba(255,255,255,0.85)"
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 14.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, i.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12.5,
        color: 'var(--vb-muted)',
        marginBottom: 8
      }
    }, i.variant), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-sm)'
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: () => setQty(idx, i.qty - 1),
      style: {
        width: 28,
        height: 28,
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        color: 'var(--vb-muted)',
        fontSize: 15
      }
    }, "\u2212"), /*#__PURE__*/React.createElement("span", {
      style: {
        minWidth: 24,
        textAlign: 'center',
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
        fontWeight: 600
      }
    }, i.qty), /*#__PURE__*/React.createElement("button", {
      onClick: () => setQty(idx, i.qty + 1),
      style: {
        width: 28,
        height: 28,
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        color: 'var(--vb-muted)',
        fontSize: 15
      }
    }, "+")), /*#__PURE__*/React.createElement("button", {
      onClick: () => remove(idx),
      style: {
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        fontSize: 12.5,
        color: 'var(--vb-muted-soft)'
      }
    }, "Remove"))), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)',
        whiteSpace: 'nowrap'
      }
    }, S.money(i.price * i.qty))))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 16,
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        padding: 18
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        marginBottom: 12
      }
    }, "Delivery address"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        gridColumn: 'span 2'
      }
    }, /*#__PURE__*/React.createElement(Input, {
      placeholder: "Full name"
    })), /*#__PURE__*/React.createElement(Input, {
      placeholder: "Phone"
    }), /*#__PURE__*/React.createElement(Input, {
      placeholder: "PIN code"
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        gridColumn: 'span 2'
      }
    }, /*#__PURE__*/React.createElement(Input, {
      placeholder: "Address line 1"
    })), /*#__PURE__*/React.createElement(Input, {
      placeholder: "City"
    }), /*#__PURE__*/React.createElement(Input, {
      placeholder: "State"
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        gridColumn: 'span 2'
      }
    }, /*#__PURE__*/React.createElement(Input, {
      placeholder: "GSTIN (optional \u2014 for business invoice)"
    }))))), /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'sticky',
        top: 80,
        display: 'flex',
        flexDirection: 'column',
        gap: 14
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        padding: 18,
        display: 'flex',
        flexDirection: 'column',
        gap: 9
      }
    }, /*#__PURE__*/React.createElement(CartRow, {
      label: "Subtotal",
      value: S.money(subtotal)
    }), applied ? /*#__PURE__*/React.createElement(CartRow, {
      label: "Discount (CHAI10)",
      value: '−' + S.money(discount),
      muted: true
    }) : null, redeem ? /*#__PURE__*/React.createElement(CartRow, {
      label: `Points (${S.rewards.points})`,
      value: '−' + S.money(pointsValue),
      muted: true
    }) : null, /*#__PURE__*/React.createElement(CartRow, {
      label: "Shipping",
      value: shipping === 0 ? 'Free' : S.money(shipping),
      muted: shipping === 0
    }), /*#__PURE__*/React.createElement(CartRow, {
      label: "GST (5%)",
      value: S.money(tax),
      muted: true
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        borderTop: '1px solid var(--vb-hairline)',
        paddingTop: 10,
        marginTop: 2
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 15,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, "Total"), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 22,
        fontWeight: 600,
        letterSpacing: '-0.6px',
        color: 'var(--vb-ink)'
      }
    }, S.money(total))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 8,
        marginTop: 6
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1
      }
    }, /*#__PURE__*/React.createElement(Input, {
      placeholder: "Discount code"
    })), /*#__PURE__*/React.createElement(Button, {
      variant: "secondary",
      onClick: () => {
        setApplied(true);
        setCode('CHAI10');
      }
    }, "Apply")), applied ? /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 12.5,
        color: '#157a3a'
      }
    }, "Code applied \u2014 you save ", S.money(discount), ".") : null, /*#__PURE__*/React.createElement(Button, {
      fullWidth: true,
      size: "lg",
      style: {
        marginTop: 6
      },
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Lock",
        size: 15,
        color: "#fff"
      })
    }, "Checkout \xB7 ", S.money(total)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        justifycontent: 'center',
        gap: 6,
        fontSize: 11.5,
        color: 'var(--vb-muted-soft)',
        justifyContent: 'center'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "ShieldCheck",
      size: 13,
      color: "var(--vb-muted-soft)"
    }), "Secured by Razorpay \xB7 UPI, cards, netbanking")), /*#__PURE__*/React.createElement("div", {
      style: {
        background: 'var(--vb-surface-card)',
        borderRadius: 'var(--radius-lg)',
        padding: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 8
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Gift",
      size: 16,
      color: "var(--vb-pink)"
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, "Rewards"), /*#__PURE__*/React.createElement(Badge, {
      tone: "ochre",
      style: {
        marginLeft: 'auto'
      }
    }, S.rewards.tier)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        color: 'var(--vb-body)'
      }
    }, "Redeem ", S.rewards.points, " points (\u2212", S.money(S.rewards.points * 100), ")"), /*#__PURE__*/React.createElement(Switch, {
      checked: redeem,
      onChange: setRedeem,
      size: "sm"
    })))), /*#__PURE__*/React.createElement("div", {
      style: {
        gridColumn: 'span 2'
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 20,
        fontWeight: 600,
        letterSpacing: '-0.5px',
        color: 'var(--vb-ink)',
        margin: '8px 0 12px'
      }
    }, "You might also like"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 14
      }
    }, crossSell.map(p => /*#__PURE__*/React.createElement("button", {
      key: p.id,
      onClick: () => onNav('product', p.id),
      style: {
        textAlign: 'left',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--vb-canvas)',
        cursor: 'pointer',
        overflow: 'hidden',
        padding: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        height: 96,
        background: S.tint(p.img),
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Leaf",
      size: 26,
      color: "rgba(255,255,255,0.85)"
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 10
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, p.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        color: 'var(--vb-body)',
        marginTop: 2
      }
    }, S.money(p.price))))))));
  }
  window.SHOPCart = Cart;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/storefront/CartScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/storefront/HomeScreen.jsx
try { (() => {
// Appu storefront — Home (hero + trust bar + catalog grid).
(function () {
  const {
    Button,
    Badge
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const S = window.SHOP;
  const {
    TrustBar,
    ProductCard
  } = window.SHOPChrome;
  function Hero({
    onNav
  }) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'relative',
        overflow: 'hidden',
        borderRadius: 'var(--radius-xl)',
        background: 'linear-gradient(150deg, var(--vb-surface-soft), var(--vb-surface-strong))',
        padding: '48px 44px',
        marginBottom: 24
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        width: 150,
        height: 150,
        borderRadius: '46% 54% 58% 42% / 52% 44% 56% 48%',
        background: 'var(--vb-pink)',
        top: -30,
        right: 60,
        opacity: 0.85
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        width: 110,
        height: 110,
        borderRadius: '46% 54% 58% 42% / 52% 44% 56% 48%',
        background: 'var(--vb-ochre)',
        bottom: -28,
        right: 200,
        opacity: 0.8
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        width: 90,
        height: 90,
        borderRadius: '46% 54% 58% 42% / 52% 44% 56% 48%',
        background: 'var(--vb-mint)',
        top: 40,
        right: 8,
        opacity: 0.8
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'relative',
        maxWidth: 460
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: "pink",
      dot: true
    }, "Fresh harvest \xB7 2026"), /*#__PURE__*/React.createElement("h1", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 44,
        fontWeight: 500,
        letterSpacing: '-1.8px',
        lineHeight: 1.05,
        margin: '14px 0 0',
        color: 'var(--vb-ink)'
      }
    }, "Chai worth slowing down for."), /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 16,
        lineHeight: 1.55,
        color: 'var(--vb-body)',
        margin: '14px 0 0',
        maxWidth: 400
      }
    }, "Single-estate Indian teas, hand-blended in small batches and shipped fresh to your door."), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 10,
        marginTop: 22
      }
    }, /*#__PURE__*/React.createElement(Button, {
      size: "lg",
      onClick: () => onNav('product', 'masala-chai'),
      trailingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "ArrowRight",
        size: 16,
        color: "#fff"
      })
    }, "Shop bestsellers"), /*#__PURE__*/React.createElement(Button, {
      size: "lg",
      variant: "secondary"
    }, "Build a gift box"))));
  }
  function Home({
    onNav,
    onAdd
  }) {
    return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Hero, {
      onNav: onNav
    }), /*#__PURE__*/React.createElement(TrustBar, null), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        marginBottom: 16
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 24,
        fontWeight: 600,
        letterSpacing: '-0.6px',
        color: 'var(--vb-ink)',
        margin: 0
      }
    }, "Our teas"), /*#__PURE__*/React.createElement("a", {
      style: {
        fontSize: 14,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        cursor: 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5
      }
    }, "View all", /*#__PURE__*/React.createElement(Icon, {
      name: "ArrowRight",
      size: 14,
      color: "currentColor"
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 18
      }
    }, S.products.map(p => /*#__PURE__*/React.createElement(ProductCard, {
      key: p.id,
      p: p,
      onNav: onNav,
      onAdd: onAdd
    }))));
  }
  window.SHOPHome = Home;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/storefront/HomeScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/storefront/ProductScreen.jsx
try { (() => {
// Appu storefront — Product detail (gallery, variants, subscribe & save, specs, FBT, reviews).
(function () {
  const {
    Button,
    Badge,
    Input
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const S = window.SHOP;
  const {
    Stars
  } = window.SHOPChrome;
  const INTERVAL = {
    WEEKLY: 'Every week',
    BIWEEKLY: 'Every 2 weeks',
    MONTHLY: 'Every month',
    QUARTERLY: 'Every 3 months'
  };
  function Product({
    onNav,
    onAdd
  }) {
    const p = S.products.find(x => x.id === S.detail.id);
    const d = S.detail;
    const [imgIdx, setImgIdx] = React.useState(0);
    const [size, setSize] = React.useState('250g');
    const [qty, setQty] = React.useState(1);
    const [sub, setSub] = React.useState(false);
    const [interval, setInterval] = React.useState('MONTHLY');
    const sale = p.compareAt && p.compareAt > p.price;
    const subPrice = Math.round(p.price * (1 - d.sub.discountPercent / 100));
    const fbt = d.fbt.map(id => S.products.find(x => x.id === id));
    return /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: 760,
        margin: '0 auto'
      }
    }, /*#__PURE__*/React.createElement("nav", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 7,
        fontSize: 13,
        color: 'var(--vb-muted)',
        marginBottom: 14
      }
    }, /*#__PURE__*/React.createElement("a", {
      onClick: () => onNav('home'),
      style: {
        cursor: 'pointer'
      }
    }, "Home"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-hairline)'
      }
    }, "/"), /*#__PURE__*/React.createElement("a", {
      onClick: () => onNav('home'),
      style: {
        cursor: 'pointer'
      }
    }, "Shop"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-hairline)'
      }
    }, "/"), /*#__PURE__*/React.createElement("span", {
      style: {
        color: 'var(--vb-body)'
      }
    }, p.title)), /*#__PURE__*/React.createElement("div", {
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-xl)',
        padding: 24,
        boxShadow: 'var(--shadow-soft)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 28
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        aspectRatio: '1',
        borderRadius: 'var(--radius-lg)',
        background: S.tint(d.images[imgIdx]),
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Leaf",
      size: 64,
      color: "rgba(255,255,255,0.85)"
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 8,
        marginTop: 10
      }
    }, d.images.map((im, i) => /*#__PURE__*/React.createElement("button", {
      key: i,
      onClick: () => setImgIdx(i),
      style: {
        width: 56,
        height: 56,
        borderRadius: 'var(--radius-sm)',
        background: S.tint(im),
        border: i === imgIdx ? '2px solid var(--vb-ink)' : '2px solid transparent',
        cursor: 'pointer'
      }
    })))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h1", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 28,
        fontWeight: 600,
        letterSpacing: '-0.8px',
        margin: 0,
        color: 'var(--vb-ink)'
      }
    }, p.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        color: 'var(--vb-muted)',
        marginTop: 2
      }
    }, p.brand), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 7,
        marginTop: 8
      }
    }, /*#__PURE__*/React.createElement(Stars, {
      value: p.rating,
      size: 15
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        color: 'var(--vb-muted)'
      }
    }, p.rating, " \xB7 ", p.reviews, " reviews")), /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 14.5,
        lineHeight: 1.55,
        color: 'var(--vb-body)',
        margin: '14px 0 0'
      }
    }, p.desc), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 18
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 600,
        color: 'var(--vb-body-strong)',
        marginBottom: 8
      }
    }, "Size"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 8
      }
    }, d.options[0].values.map(val => /*#__PURE__*/React.createElement("button", {
      key: val,
      onClick: () => setSize(val),
      style: {
        padding: '8px 16px',
        borderRadius: 'var(--radius-md)',
        cursor: 'pointer',
        fontFamily: 'var(--font-sans)',
        fontSize: 14,
        fontWeight: 600,
        border: '1px solid ' + (size === val ? 'var(--vb-ink)' : 'var(--vb-hairline)'),
        background: size === val ? 'var(--vb-ink)' : 'var(--vb-canvas)',
        color: size === val ? '#fff' : 'var(--vb-ink)'
      }
    }, val)))), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'baseline',
        gap: 10,
        marginTop: 18
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 30,
        fontWeight: 600,
        letterSpacing: '-1px',
        color: 'var(--vb-ink)'
      }
    }, S.money(sub ? subPrice : p.price)), sale && !sub ? /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 16,
        color: 'var(--vb-muted-soft)',
        textDecoration: 'line-through'
      }
    }, S.money(p.compareAt)) : null, sale && !sub ? /*#__PURE__*/React.createElement(Badge, {
      tone: "pink"
    }, Math.round((1 - p.price / p.compareAt) * 100), "% off") : null), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 16,
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)',
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        gap: 10
      }
    }, /*#__PURE__*/React.createElement("label", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        fontSize: 14,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        cursor: 'pointer'
      }
    }, /*#__PURE__*/React.createElement("input", {
      type: "radio",
      checked: !sub,
      onChange: () => setSub(false),
      style: {
        accentColor: 'var(--vb-ink)'
      }
    }), " One-time purchase"), /*#__PURE__*/React.createElement("label", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        fontSize: 14,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        cursor: 'pointer'
      }
    }, /*#__PURE__*/React.createElement("input", {
      type: "radio",
      checked: sub,
      onChange: () => setSub(true),
      style: {
        accentColor: 'var(--vb-ink)'
      }
    }), " Subscribe & save ", d.sub.discountPercent, "% \xB7 ", S.money(subPrice)), sub ? /*#__PURE__*/React.createElement("select", {
      value: interval,
      onChange: e => setInterval(e.target.value),
      style: {
        marginLeft: 26,
        height: 38,
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--vb-hairline)',
        padding: '0 10px',
        fontFamily: 'var(--font-sans)',
        fontSize: 13.5,
        color: 'var(--vb-ink)',
        background: 'var(--vb-canvas)'
      }
    }, d.sub.intervals.map(iv => /*#__PURE__*/React.createElement("option", {
      key: iv,
      value: iv
    }, INTERVAL[iv]))) : null), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)',
        height: 44
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: () => setQty(Math.max(1, qty - 1)),
      style: {
        width: 36,
        height: 42,
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        fontSize: 18,
        color: 'var(--vb-muted)'
      }
    }, "\u2212"), /*#__PURE__*/React.createElement("span", {
      style: {
        minWidth: 28,
        textAlign: 'center',
        fontFamily: 'var(--font-mono)',
        fontSize: 14,
        fontWeight: 600
      }
    }, qty), /*#__PURE__*/React.createElement("button", {
      onClick: () => setQty(qty + 1),
      style: {
        width: 36,
        height: 42,
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        fontSize: 18,
        color: 'var(--vb-muted)'
      }
    }, "+")), /*#__PURE__*/React.createElement(Button, {
      fullWidth: true,
      size: "lg",
      onClick: () => onAdd(p, qty),
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: sub ? 'Repeat' : 'ShoppingCart',
        size: 16,
        color: "#fff"
      })
    }, sub ? 'Subscribe' : 'Add to cart'), /*#__PURE__*/React.createElement(Button, {
      size: "lg",
      variant: "secondary",
      style: {
        padding: '0 14px'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Heart",
      size: 18,
      color: "var(--vb-ink)"
    })))))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 16,
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-lg)',
        padding: 20
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 16,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        marginBottom: 10
      }
    }, "Details"), /*#__PURE__*/React.createElement("table", {
      style: {
        width: '100%',
        fontSize: 14
      }
    }, /*#__PURE__*/React.createElement("tbody", null, d.specs.map(([k, v]) => /*#__PURE__*/React.createElement("tr", {
      key: k,
      style: {
        borderBottom: '1px solid var(--vb-hairline-soft)'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '9px 0',
        color: 'var(--vb-muted)',
        width: '40%'
      }
    }, k), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: '9px 0',
        color: 'var(--vb-body-strong)',
        fontWeight: 500
      }
    }, v)))))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 20,
        fontWeight: 600,
        letterSpacing: '-0.5px',
        color: 'var(--vb-ink)',
        margin: '0 0 12px'
      }
    }, "Frequently bought together"), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        flexWrap: 'wrap'
      }
    }, fbt.map(f => /*#__PURE__*/React.createElement("button", {
      key: f.id,
      onClick: () => onNav('product', f.id),
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: 10,
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)',
        cursor: 'pointer'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 44,
        height: 44,
        borderRadius: 'var(--radius-sm)',
        background: S.tint(f.img),
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flex: 'none'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Leaf",
      size: 18,
      color: "rgba(255,255,255,0.85)"
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        textAlign: 'left'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'block',
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, f.title), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        color: 'var(--vb-muted)'
      }
    }, S.money(f.price))))), /*#__PURE__*/React.createElement(Button, {
      variant: "secondary",
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Plus",
        size: 14,
        color: "var(--vb-ink)"
      })
    }, "Add all 3 \xB7 save 12%"))), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        marginBottom: 12
      }
    }, /*#__PURE__*/React.createElement("h2", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 20,
        fontWeight: 600,
        letterSpacing: '-0.5px',
        color: 'var(--vb-ink)',
        margin: 0
      }
    }, "Reviews"), /*#__PURE__*/React.createElement(Stars, {
      value: p.rating,
      size: 16
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13.5,
        color: 'var(--vb-muted)'
      }
    }, p.rating, " out of 5 \xB7 ", p.reviews)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 10
      }
    }, d.reviewList.map((r, i) => /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-md)',
        padding: 16
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13.5,
        fontWeight: 600,
        color: 'var(--vb-ink)'
      }
    }, r.name), r.verified ? /*#__PURE__*/React.createElement(Badge, {
      tone: "success",
      dot: true
    }, "Verified") : null, /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: 'auto',
        fontSize: 12,
        color: 'var(--vb-muted-soft)'
      }
    }, r.when)), /*#__PURE__*/React.createElement("div", {
      style: {
        margin: '6px 0'
      }
    }, /*#__PURE__*/React.createElement(Stars, {
      value: r.rating,
      size: 13
    })), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: 0,
        fontSize: 14,
        lineHeight: 1.5,
        color: 'var(--vb-body)'
      }
    }, r.body))))));
  }
  window.SHOPProduct = Product;
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/storefront/ProductScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/storefront/StoreChrome.jsx
try { (() => {
// Appu storefront — shared chrome: header, footer, trust bar, stars, product card.
(function () {
  const {
    Badge,
    Button
  } = window.VibrantDesignSystem_7e2fbe;
  const Icon = window.Icon;
  const S = window.SHOP;
  function Stars({
    value,
    size = 14
  }) {
    return /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        gap: 1
      }
    }, [0, 1, 2, 3, 4].map(i => /*#__PURE__*/React.createElement(Icon, {
      key: i,
      name: "Star",
      size: size,
      color: i < Math.round(value) ? 'var(--vb-ochre)' : 'var(--vb-hairline)',
      style: {
        fill: i < Math.round(value) ? 'var(--vb-ochre)' : 'transparent'
      }
    })));
  }
  function Header({
    cartCount,
    onNav
  }) {
    return /*#__PURE__*/React.createElement("header", {
      style: {
        position: 'sticky',
        top: 0,
        zIndex: 20,
        background: 'rgba(255,250,240,0.85)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--vb-hairline)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: 1040,
        margin: '0 auto',
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        padding: '12px 24px'
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: () => onNav('home'),
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        padding: 0
      }
    }, /*#__PURE__*/React.createElement("img", {
      src: window.__resources && window.__resources.mark || "../../assets/vibrant-mark.svg",
      width: "26",
      height: "26",
      alt: ""
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 21,
        fontWeight: 600,
        letterSpacing: '-0.7px',
        color: 'var(--vb-ink)'
      }
    }, S.store.name)), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        position: 'relative',
        maxWidth: 380
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Search",
      size: 15,
      color: "var(--vb-muted)",
      style: {
        position: 'absolute',
        left: 13,
        top: 12
      }
    }), /*#__PURE__*/React.createElement("input", {
      placeholder: "Search teas\u2026",
      style: {
        width: '100%',
        height: 40,
        padding: '0 14px 0 36px',
        borderRadius: 'var(--radius-pill)',
        border: '1px solid var(--vb-hairline)',
        background: 'var(--vb-surface-soft)',
        fontFamily: 'var(--font-sans)',
        fontSize: 14,
        color: 'var(--vb-ink)',
        outline: 'none'
      }
    })), /*#__PURE__*/React.createElement("nav", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        marginLeft: 'auto'
      }
    }, /*#__PURE__*/React.createElement("a", {
      style: {
        fontSize: 14,
        color: 'var(--vb-muted)',
        cursor: 'pointer'
      }
    }, "Track"), /*#__PURE__*/React.createElement("a", {
      onClick: () => onNav('home'),
      style: {
        fontSize: 14,
        fontWeight: 600,
        color: 'var(--vb-ink)',
        cursor: 'pointer'
      }
    }, "Shop"), /*#__PURE__*/React.createElement(Icon, {
      name: "User",
      size: 20,
      color: "var(--vb-ink)",
      style: {
        cursor: 'pointer'
      }
    }), /*#__PURE__*/React.createElement(Icon, {
      name: "Heart",
      size: 20,
      color: "var(--vb-ink)",
      style: {
        cursor: 'pointer'
      }
    }), /*#__PURE__*/React.createElement("button", {
      onClick: () => onNav('cart'),
      style: {
        position: 'relative',
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        padding: 0,
        display: 'inline-flex'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "ShoppingCart",
      size: 20,
      color: "var(--vb-ink)"
    }), cartCount > 0 ? /*#__PURE__*/React.createElement("span", {
      style: {
        position: 'absolute',
        right: -8,
        top: -8,
        minWidth: 16,
        height: 16,
        padding: '0 4px',
        borderRadius: 'var(--radius-pill)',
        background: 'var(--vb-pink)',
        color: '#fff',
        fontSize: 10,
        fontWeight: 700,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center'
      }
    }, cartCount) : null))));
  }
  function TrustBar() {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexWrap: 'wrap',
        gap: 10,
        marginBottom: 22
      }
    }, S.trust.map(t => /*#__PURE__*/React.createElement("span", {
      key: t.text,
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 14px',
        background: 'var(--vb-surface-card)',
        borderRadius: 'var(--radius-pill)',
        fontSize: 13,
        fontWeight: 500,
        color: 'var(--vb-body-strong)'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: t.icon,
      size: 15,
      color: "var(--vb-teal)"
    }), t.text)));
  }
  function ProductCard({
    p,
    onNav,
    onAdd
  }) {
    const sale = p.compareAt && p.compareAt > p.price;
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--vb-canvas)',
        border: '1px solid var(--vb-hairline)',
        borderRadius: 'var(--radius-xl)',
        overflow: 'hidden',
        boxShadow: 'var(--shadow-soft)'
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: () => onNav('product', p.id),
      style: {
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        padding: 0,
        textAlign: 'left'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'relative',
        height: 180,
        background: window.SHOP.tint(p.img),
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "Leaf",
      size: 42,
      color: "rgba(255,255,255,0.85)"
    }), p.tag ? /*#__PURE__*/React.createElement("span", {
      style: {
        position: 'absolute',
        top: 12,
        left: 12
      }
    }, /*#__PURE__*/React.createElement(Badge, {
      tone: p.tag === 'New' ? 'teal' : 'pink',
      dot: true
    }, p.tag)) : null, p.avail === 'out_of_stock' ? /*#__PURE__*/React.createElement("span", {
      style: {
        position: 'absolute',
        inset: 0,
        background: 'rgba(255,250,240,0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        background: 'var(--vb-ink)',
        color: '#fff',
        fontSize: 12,
        fontWeight: 600,
        padding: '5px 12px',
        borderRadius: 'var(--radius-pill)'
      }
    }, "Sold out")) : null)), /*#__PURE__*/React.createElement("div", {
      style: {
        padding: 16,
        display: 'flex',
        flexDirection: 'column',
        flex: 1
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: () => onNav('product', p.id),
      style: {
        border: 'none',
        background: 'none',
        cursor: 'pointer',
        padding: 0,
        textAlign: 'left'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 16.5,
        fontWeight: 600,
        letterSpacing: '-0.3px',
        color: 'var(--vb-ink)'
      }
    }, p.title)), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        marginTop: 4
      }
    }, /*#__PURE__*/React.createElement(Stars, {
      value: p.rating,
      size: 13
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: 'var(--vb-muted-soft)'
      }
    }, "(", p.reviews, ")"), p.avail === 'low_stock' ? /*#__PURE__*/React.createElement(Badge, {
      tone: "warning",
      style: {
        marginLeft: 'auto'
      }
    }, "Low stock") : null), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: '8px 0 0',
        fontSize: 13,
        lineHeight: 1.5,
        color: 'var(--vb-muted)',
        display: '-webkit-box',
        WebkitLineClamp: 2,
        WebkitBoxOrient: 'vertical',
        overflow: 'hidden'
      }
    }, p.desc), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 'auto',
        paddingTop: 14,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: 6
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 18,
        fontWeight: 600,
        letterSpacing: '-0.4px',
        color: 'var(--vb-ink)'
      }
    }, S.money(p.price)), sale ? /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 13,
        color: 'var(--vb-muted-soft)',
        textDecoration: 'line-through'
      }
    }, S.money(p.compareAt)) : null), /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      disabled: p.avail === 'out_of_stock',
      onClick: () => onAdd(p),
      leadingIcon: /*#__PURE__*/React.createElement(Icon, {
        name: "Plus",
        size: 14,
        color: p.avail === 'out_of_stock' ? 'var(--vb-muted-soft)' : '#fff'
      })
    }, "Add"))));
  }
  function Footer() {
    const cols = {
      Shop: ['All teas', 'Chai', 'Green & herbal', 'Gifting'],
      Help: ['Track order', 'Returns', 'Shipping', 'Contact'],
      Saanjh: ['Our story', 'Sourcing', 'Wholesale', 'Stores']
    };
    return /*#__PURE__*/React.createElement("footer", {
      style: {
        borderTop: '1px solid var(--vb-hairline)',
        background: 'var(--vb-surface-soft)',
        marginTop: 48
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        maxWidth: 1040,
        margin: '0 auto',
        padding: '40px 24px',
        display: 'grid',
        gridTemplateColumns: '1.4fr repeat(3, 1fr)',
        gap: 28
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        alignItems: 'center',
        gap: 9,
        marginBottom: 10
      }
    }, /*#__PURE__*/React.createElement("img", {
      src: window.__resources && window.__resources.mark || "../../assets/vibrant-mark.svg",
      width: "22",
      height: "22",
      alt: ""
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-display)',
        fontSize: 19,
        fontWeight: 600,
        letterSpacing: '-0.6px'
      }
    }, S.store.name)), /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 13,
        color: 'var(--vb-muted)',
        lineHeight: 1.5,
        maxWidth: 220,
        margin: 0
      }
    }, S.store.tagline, " \u2014 single-estate teas, freshly packed and shipped across India.")), Object.entries(cols).map(([h, links]) => /*#__PURE__*/React.createElement("div", {
      key: h
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 12,
        fontWeight: 600,
        letterSpacing: '0.5px',
        textTransform: 'uppercase',
        color: 'var(--vb-ink)',
        marginBottom: 12
      }
    }, h), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        flexDirection: 'column',
        gap: 9
      }
    }, links.map(l => /*#__PURE__*/React.createElement("a", {
      key: l,
      style: {
        fontSize: 13,
        color: 'var(--vb-muted)',
        cursor: 'pointer'
      }
    }, l)))))));
  }
  window.SHOPChrome = {
    Header,
    Footer,
    TrustBar,
    Stars,
    ProductCard
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/storefront/StoreChrome.jsx", error: String((e && e.message) || e) }); }

// ui_kits/storefront/data.jsx
try { (() => {
// Appu storefront — mock catalog for a demo India tea store (₹ / INR).
(function () {
  const money = paise => '₹' + (paise / 100).toLocaleString('en-IN');
  window.SHOP = {
    money,
    store: {
      name: 'Saanjh',
      tagline: 'Indian Tea Co.'
    },
    trust: [{
      icon: 'Truck',
      text: 'Free delivery over ₹499'
    }, {
      icon: 'RotateCcw',
      text: '7-day easy returns'
    }, {
      icon: 'ShieldCheck',
      text: 'Secure checkout'
    }, {
      icon: 'Leaf',
      text: 'Single-estate, fresh'
    }],
    products: [{
      id: 'masala-chai',
      title: 'Masala Chai',
      brand: 'Saanjh',
      price: 34900,
      compareAt: 42000,
      rating: 4.7,
      reviews: 128,
      avail: 'in_stock',
      tag: 'Bestseller',
      desc: 'A bold Assam CTC base with hand-pounded cardamom, ginger, clove and cinnamon. Brews thick, malty and fragrant.',
      img: 'pink'
    }, {
      id: 'darjeeling',
      title: 'Darjeeling First Flush',
      brand: 'Saanjh',
      price: 54000,
      rating: 4.9,
      reviews: 86,
      avail: 'in_stock',
      tag: 'New',
      desc: 'The “champagne of teas” — bright, floral and delicate, plucked in the first spring flush.',
      img: 'ochre'
    }, {
      id: 'tulsi-green',
      title: 'Tulsi Green',
      brand: 'Saanjh',
      price: 29900,
      rating: 4.6,
      reviews: 54,
      avail: 'low_stock',
      desc: 'Holy basil and green tea — calming, herbaceous, lightly sweet.',
      img: 'mint'
    }, {
      id: 'cardamom-chai',
      title: 'Cardamom Chai',
      brand: 'Saanjh',
      price: 36900,
      rating: 4.8,
      reviews: 203,
      avail: 'in_stock',
      desc: 'Single-spice elegance: green cardamom over a smooth Assam base.',
      img: 'lavender'
    }, {
      id: 'kahwa',
      title: 'Kashmiri Kahwa',
      brand: 'Saanjh',
      price: 48000,
      compareAt: 56000,
      rating: 4.5,
      reviews: 37,
      avail: 'in_stock',
      desc: 'Saffron, almond and whole spices — a golden, festive brew.',
      img: 'peach'
    }, {
      id: 'lemongrass',
      title: 'Lemongrass Herbal',
      brand: 'Saanjh',
      price: 27500,
      rating: 4.4,
      reviews: 61,
      avail: 'out_of_stock',
      desc: 'Caffeine-free, zesty and bright. A clean afternoon cup.',
      img: 'teal'
    }],
    // Product-detail extras (for the Masala Chai PDP)
    detail: {
      id: 'masala-chai',
      images: ['pink', 'ochre', 'mint'],
      options: [{
        name: 'Size',
        values: ['100g', '250g', '500g']
      }],
      sub: {
        enabled: true,
        discountPercent: 10,
        intervals: ['WEEKLY', 'BIWEEKLY', 'MONTHLY', 'QUARTERLY']
      },
      specs: [['Tea type', 'Black (CTC + spices)'], ['Origin', 'Assam, India'], ['Caffeine', 'Medium–high'], ['Steep', '4–5 min · 95°C']],
      country: 'India',
      fbt: ['cardamom-chai', 'kahwa'],
      reviewList: [{
        name: 'Ananya R.',
        rating: 5,
        verified: true,
        when: '2 weeks ago',
        body: 'Tastes exactly like my grandmother’s kitchen. The cardamom is so fresh.'
      }, {
        name: 'Vikram S.',
        rating: 5,
        verified: true,
        when: '1 month ago',
        body: 'Strong and malty — holds up beautifully to milk and a bit of jaggery.'
      }, {
        name: 'Priya M.',
        rating: 4,
        verified: false,
        when: '1 month ago',
        body: 'Lovely aroma. Wish the 500g came in a tin rather than a pouch.'
      }]
    },
    cart: [{
      id: 'masala-chai',
      title: 'Masala Chai',
      variant: '250g',
      price: 34900,
      qty: 2,
      img: 'pink'
    }, {
      id: 'cardamom-chai',
      title: 'Cardamom Chai',
      variant: '250g',
      price: 36900,
      qty: 1,
      img: 'lavender'
    }],
    rewards: {
      enabled: true,
      found: true,
      points: 240,
      tier: 'Silver',
      minRedeem: 100
    }
  };

  // Map a product's "img" key to a warm brand-tint placeholder gradient.
  window.SHOP.tint = function (key) {
    const c = {
      pink: 'var(--vb-pink)',
      ochre: 'var(--vb-ochre)',
      mint: 'var(--vb-mint)',
      lavender: 'var(--vb-lavender)',
      peach: 'var(--vb-peach)',
      teal: 'var(--vb-teal)'
    }[key] || 'var(--vb-surface-card)';
    return 'radial-gradient(120% 120% at 30% 25%, color-mix(in oklch, ' + c + ' 55%, white), color-mix(in oklch, ' + c + ' 22%, white))';
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/storefront/data.jsx", error: String((e && e.message) || e) }); }

__ds_ns.FeatureCard = __ds_scope.FeatureCard;

__ds_ns.StatCard = __ds_scope.StatCard;

__ds_ns.Avatar = __ds_scope.Avatar;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Switch = __ds_scope.Switch;

__ds_ns.Tabs = __ds_scope.Tabs;

})();

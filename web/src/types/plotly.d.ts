declare module "plotly.js-basic-dist-min" {
  // Not `import type`: this needs to carry the value declarations (Plotly.react, Plotly.purge,
  // ...) as well as the types, and since this whole block is an ambient `declare module`, it
  // emits no JS either way -- there is no real "plotly.js" runtime package to resolve against.
  import * as Plotly from "plotly.js";
  export = Plotly;
}

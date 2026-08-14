// The reading half of `autocircuit/core/wire.py`, and deliberately only that half.
//
// Payloads arrive from Python as JSON and are kept exactly as they arrived: the main thread
// stores a spectrum as its wire object and hands the same object back when it asks for a trim
// or a validation. Nothing here re-encodes a number, so there is no second implementation of
// the float format to keep in step with Python's -- decoding is for drawing pictures, and a
// picture is the one thing that cannot be sent back.
//
// Non-finite values travel as the string sentinels "inf", "-inf" and "nan". They are not an
// edge case: an exact fit on noise-free data has a residual sum of squares of zero, which makes
// its information criteria -inf.

export type WireFloat = number | string;

export interface WireArray {
  shape: number[];
  data: WireFloat[];
}

export interface WireComplexArray {
  shape: number[];
  re: WireFloat[];
  im: WireFloat[];
}

export function decodeFloat(value: WireFloat): number {
  if (typeof value === "number") return value;
  switch (value) {
    case "inf":
      return Number.POSITIVE_INFINITY;
    case "-inf":
      return Number.NEGATIVE_INFINITY;
    case "nan":
      return Number.NaN;
    default:
      throw new Error(`unknown float sentinel ${JSON.stringify(value)}`);
  }
}

function decodeFlat(data: WireFloat[]): Float64Array {
  const out = new Float64Array(data.length);
  for (let i = 0; i < data.length; i += 1) out[i] = decodeFloat(data[i] as WireFloat);
  return out;
}

export function decodeArray(payload: WireArray): Float64Array {
  return decodeFlat(payload.data);
}

export function decodeComplexArray(payload: WireComplexArray): {
  re: Float64Array;
  im: Float64Array;
} {
  return { re: decodeFlat(payload.re), im: decodeFlat(payload.im) };
}

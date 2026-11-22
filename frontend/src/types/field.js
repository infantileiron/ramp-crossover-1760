/** @typedef {{code:string, sequence:'AB'|'BA', period1:number|null, period2:number|null, batch_id:number|null, batch_label:string|null, entry_status:string|null}} FieldPair */

/** @param {FieldPair} row */
export function isComplete(row) {
  return row.period1 !== null && row.period2 !== null;
}

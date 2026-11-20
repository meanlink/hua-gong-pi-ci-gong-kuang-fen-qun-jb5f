/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,blind_lock_id:number|null}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {'sealed'|'unblinding'|'revealed'} BlindStatus */
/** @typedef {{id:number,name:string,rows:number,checksum:string,baseline_job_id:number,status:BlindStatus,records?:Array,result?:Object,revealed_at:number|null}} BlindTrial */
export {};

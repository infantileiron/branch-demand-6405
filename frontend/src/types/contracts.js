/** @typedef {{id:number,branch:string,day:string,volume:number,note:string}} DailyVolume */
/** @typedef {{id:number,name:string,branch:string,backtest_days:number,alpha:number,beta:number,state:string,result:object}} ForecastRun */
/** @typedef {{id:number,run_id:number,capacity:number,model:string,schedule:object[],status:string}} Staffing */

/** @typedef {{id:number,name:string,note:string,members:string[],runs:object[],staffings:object[]}} Region */
/** @typedef {{id:number,region_id:number,week:string,version:number,state:string,error:string,published_at:string,superseded_by:number|null,members:object[],result:object}} RegionRun */
/** @typedef {{id:number,region_id:number,region_run_id:number,branch:string,week:string,capacity:number,model:string,schedule:object[],basis:object,status:string}} RegionStaffing */

package de.youspeed.android.alpha

import kotlin.math.roundToInt

internal class TripStopPromptPolicy {
    private var driven=false
    private var stationary=false
    private var stoppedSince:Double?=null
    private var lastFix:Double?=null
    private var continued=false
    fun observe(speed:Double,at:Double,usable:Boolean,recording:Boolean) {
        if(!recording) {driven=false;stationary=false;stoppedSince=null;lastFix=null;continued=false;return}
        if(!usable || !at.isFinite() || !speed.isFinite() || speed<0) {stoppedSince=null;lastFix=null;stationary=false;return}
        if(lastFix?.let {at<=it}==true) return
        if(lastFix?.let {at-it>3}==true) stoppedSince=null
        lastFix=at
        stationary=speed<=0.28
        if(speed>0.28) {stoppedSince=null;continued=false;if(speed>=1) driven=true;return}
        if(driven && !continued && stoppedSince==null) stoppedSince=at
    }
    fun visible(at:Double):Boolean {val last=lastFix ?: return false;val start=stoppedSince ?: return false
        return !continued && at>=last && at-last<=3 && last-start>=15}
    fun canStop(at:Double):Boolean {val last=lastFix ?: return false
        return !continued && stationary && at>=last && at-last<=3}
    fun continueTrip() {continued=true;stoppedSince=null}
}
internal data class TripStopPromptSnapshot(val tripID:String,val reading:Int,val estimated:Boolean)
internal object TripOdometer {
    fun estimate(last:Double?,distance:Double):Int {
        if(last==null || !last.isFinite() || last<0 || !distance.isFinite()) return 0
        return (last+distance.coerceAtLeast(0.0)/1000).coerceIn(0.0,999999.0).roundToInt()
    }
    fun replacingDigit(reading:Int,index:Int,digit:Int):Int {
        val place=listOf(100000,10000,1000,100,10,1)[index]
        return reading-(reading/place%10)*place+digit*place
    }
}

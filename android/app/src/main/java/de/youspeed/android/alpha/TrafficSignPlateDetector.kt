package de.youspeed.android.alpha

import kotlin.math.*

/** Native top-left coordinates; shared detection semantics with iPhone. */
data class TrafficSignPlateRect(val x: Int, val y: Int, val width: Int, val height: Int)
internal object TrafficSignPlateDetector {
    const val revision = "bounded-plate-frame-v1"
    data class Scan(val rect:TrafficSignPlateRect?,val plates:List<TrafficSignPlateRect>,val status:String,
        val decision:String,val lowerLumaStd:Double,val lowerEdgeFraction:Double,val backgroundVerified:Boolean=false)
    fun select(width:Int,height:Int,argb:IntArray):TrafficSignPlateRect? = scan(width,height,argb).rect
    fun scan(width: Int, height: Int, argb: IntArray): Scan {
        fun unresolved(reason:String)=Scan(null,emptyList(),"unresolved",reason,Double.POSITIVE_INFINITY,1.0)
        if (width < 48 || height < 64 || width.toLong()*height > 4_000_000 || argb.size.toLong() != width.toLong()*height) return unresolved("invalid_context_pixels")
        val half=height/2; val overlap=min(half,max(5,min(16,(width*.08).roundToInt())))
        val start=half-overlap;val nativeHeight=height-start;val factor=max(1.0,max(width,nativeHeight)/640.0)
        val w=max(1,(width/factor).toInt());val h=max(1,(nativeHeight/factor).toInt())
        val luminance=DoubleArray(w*h);val neutral=BooleanArray(w*h)
        for(y in 0 until h) for(x in 0 until w) {
            val sx=min(width-1,(x*factor).toInt());val sy=min(height-1,start+(y*factor).toInt());val pixel=argb[sy*width+sx]
            val r=(pixel ushr 16 and 255).toDouble();val g=(pixel ushr 8 and 255).toDouble();val b=(pixel and 255).toDouble();val level=(r+g+b)/3
            luminance[y*w+x]=level;neutral[y*w+x]=maxOf(r,g,b)-minOf(r,g,b)<=65 || (b>=g && g>=r && b-r<=max(65.0,level*.5))
        }
        val brightness=luminance.sortedArray()[(luminance.size*.9).toInt()]
        var ambiguousPanel=false
        val lowerLevels=mutableListOf<Double>();var edgeCount=0;var edgeTotal=0
        for(y in half+max(2,height/40) until height-max(2,height/40)) for(x in max(2,width/20) until width-max(2,width/20)) {
            val pixel=argb[y*width+x];val value=((pixel ushr 16 and 255)+(pixel ushr 8 and 255)+(pixel and 255))/3.0
            lowerLevels+=value
            if(x>width/20+2) {val prior=argb[y*width+x-1];val previous=((prior ushr 16 and 255)+(prior ushr 8 and 255)+(prior and 255))/3.0;edgeTotal++;if(abs(value-previous)>28)edgeCount++}
        }
        val lowerMean=lowerLevels.average();val lowerStd=sqrt(lowerLevels.sumOf {(it-lowerMean).pow(2)}/max(1,lowerLevels.size))
        val lowerEdges=edgeCount.toDouble()/max(1,edgeTotal)
        for(scale in listOf(.65,.60,.55)) {
            val white=BooleanArray(w*h){neutral[it] && luminance[it]>=max(60.0,brightness*scale)};val candidates=mutableListOf<IntArray>();val potentialPanels=mutableListOf<IntArray>()
            for(seed in white.indices) {
                if(!white[seed]) continue
                white[seed]=false;val queue=ArrayList<Int>();queue.add(seed);var head=0
                var l=seed%w;var r=l;var t=seed/w;var b=t;var total=0.0
                while(head<queue.size) {
                    val i=queue[head++];val x=i%w;val y=i/w;l=min(l,x);r=max(r,x);t=min(t,y);b=max(b,y);total+=luminance[i]
                    for(other in intArrayOf(if(x>0)i-1 else -1,if(x+1<w)i+1 else -1,i-w,i+w)) {
                        if(other>=0 && other<w*h && white[other]){white[other]=false;queue.add(other)}
                    }
                }
                val cw=r-l+1;val ch=b-t+1
                if(b==h-1 && cw>=.4*w && ch in 2..11 && queue.size>=.45*cw*ch) {ambiguousPanel=true;potentialPanels+=intArrayOf(l,t,r+1,b+1)}
                if(cw>=.3*w && ch>=8 && cw.toDouble()/ch in .8..10.0 && queue.size>=.45*cw*ch &&
                    abs((l+r+1)/2.0-w/2.0)<=.35*w && (t+b)/2.0>overlap/factor) {ambiguousPanel=true;potentialPanels+=intArrayOf(l,t,r+1,b+1)}
                if(cw<.4*w || ch<12 || cw.toDouble()/ch !in 1.2..8.0 || queue.size<.6*cw*ch || abs((l+r+1)/2.0-w/2.0)>.25*w) continue
                val margin=max(2,min(5,(min(cw,ch)*.08).roundToInt()));val paper=total/queue.size
                val rowsL=IntArray(h){w};val rowsR=IntArray(h){-1};val colsT=IntArray(w){h};val colsB=IntArray(w){-1}
                for(i in queue){val x=i%w;val y=i/w;rowsL[y]=min(rowsL[y],x);rowsR[y]=max(rowsR[y],x);colsT[x]=min(colsT[x],y);colsB[x]=max(colsB[x],y)}
                val tx=max(1,(cw*.12).roundToInt());val ty=max(1,(ch*.12).roundToInt());val profiles=Array(4){mutableListOf<Pair<Int,Int>>()}
                for(x in l+tx until r+1-tx) if(colsB[x]>=0){profiles[0].add(x to colsT[x]);profiles[1].add(x to colsB[x])}
                for(y in t+ty until b+1-ty) if(rowsR[y]>=0){profiles[2].add(rowsL[y] to y);profiles[3].add(rowsR[y] to y)}
                val cuts=listOf(t==0,b==h-1,l==0,r==w-1);val directions=listOf(0 to -1,0 to 1,-1 to 0,1 to 0)
                // An open top in owned primary context is the parent board.
                if(cuts[0] || cuts[1] || cuts.count{it}>1) continue
                var frameOK=true
                for(side in 0..3) {
                    var observed=0;var hits=0;val (dx,dy)=directions[side]
                    for((x,y) in profiles[side]) {
                        val values=(1..2*margin).mapNotNull {distance->val xx=x+dx*distance;val yy=y+dy*distance;if(xx in 0 until w && yy in 0 until h)luminance[yy*w+xx] else null}
                        if(values.size<4)continue
                        observed++;val probe=min(margin,values.size/2);val inner=values.take(probe);val ink=inner.min();val offset=inner.indexOf(ink);val outside=values.drop(max(probe,offset+1))
                        if(ink<=paper*.78 && outside.isNotEmpty() && outside.average()-ink>=5)hits++
                    }
                    val unseen=observed<.5*profiles[side].size
                    if(!(cuts[side] && unseen) && hits.toDouble()/max(1,observed)<.45){frameOK=false;break}
                }
                if(!frameOK)continue
                var inkCount=0;for(y in t+2 until b-1)for(x in l+2 until r-1)if(luminance[y*w+x]<paper*.7)inkCount++
                val ink=inkCount.toDouble()/max(1,(cw-4)*(ch-4));if(ink !in .004.. .35)continue
                candidates.add(intArrayOf(max(0,l-margin),max(0,t-margin),min(w,r+margin+1),min(h,b+margin+1),l,t,r+1,b+1))
            }
            if(candidates.isEmpty() || candidates.size>3)continue
            candidates.sortBy{it[1]};var aligned=true
            for(i in 1 until candidates.size){val a=candidates[i-1];val b=candidates[i];val aw=a[2]-a[0];val bw=b[2]-b[0];val gap=b[1]-a[3]
                if(min(aw,bw)<.7*max(aw,bw) || min(a[2],b[2])-max(a[0],b[0])<.8*min(aw,bw) || gap<0 || gap>.15*min(aw,bw))aligned=false
            }
            if(!aligned)continue
            val x=floor(candidates.minOf{it[0]}*width.toDouble()/w).toInt();val top=start+floor(candidates.minOf{it[1]}*nativeHeight.toDouble()/h).toInt()
            val right=min(width,ceil(candidates.maxOf{it[2]}*width.toDouble()/w).toInt());val bottom=min(height,start+ceil(candidates.maxOf{it[3]}*nativeHeight.toDouble()/h).toInt());val y=max(half,top)
            if(right-x>=48 && bottom-y>=32 && (top+bottom)/2>half) {
                val components=candidates.map {c ->
                    val left=floor(c[4]*width.toDouble()/w).toInt();val upper=start+floor(c[5]*nativeHeight.toDouble()/h).toInt()
                    val endX=min(width,ceil(c[6]*width.toDouble()/w).toInt());val endY=min(height,start+ceil(c[7]*nativeHeight.toDouble()/h).toInt())
                    TrafficSignPlateRect(left,upper,endX-left,endY-upper)
                }
                val allPanelsAccounted=potentialPanels.all {p ->candidates.any {c ->
                    min(c[2],p[2])-max(c[0],p[0])>=.8*(p[2]-p[0]) && min(c[3],p[3])-max(c[1],p[1])>=.8*(p[3]-p[1])}}
                val complete=allPanelsAccounted && components.all {it.x>=2 && it.y>=half && it.x+it.width<=width-2 && it.y+it.height<=height-2}
                return Scan(TrafficSignPlateRect(x,y,right-x,bottom-y),components,if(complete) "complete" else "unresolved",
                    if(complete) "framed_components" else "component_context_edge",lowerStd,lowerEdges)
            }
        }
        // A missing frame alone does not prove a bare sign. Only a measured,
        // quiet lower region can supply negative plate evidence; busy scenes fail closed.
        val fullLower=(half until height).flatMap {y -> (0 until width).map {x ->val pixel=argb[y*width+x];((pixel ushr 16 and 255)+(pixel ushr 8 and 255)+(pixel and 255))/3}}
        val plain=fullLower.isNotEmpty() && fullLower.min()>=40 && fullLower.max()-fullLower.min()<=24
        val background=!plain && !ambiguousPanel && naturalBackground(width,height,argb)
        return Scan(null,emptyList(),if(plain || background) "plain" else "unresolved",
            if(plain) "quiet_lower_context" else if(background) "natural_background_without_panel" else if(ambiguousPanel) "unread_or_ambiguous_panel" else "unresolved_lower_region",lowerStd,lowerEdges,background)
    }
    fun naturalBackground(width:Int,height:Int,argb:IntArray):Boolean {
        if(width<80 || height<128 || argb.size!=width*height) return false
        val w=64;val h=48;val colors=IntArray(w*h);var vegetation=0;var dark=0
        for(y in 0 until h)for(x in 0 until w) {
            val p=argb[(height/2+y*(height-height/2)/h)*width+x*width/w]
            val r=p ushr 16 and 255;val g=p ushr 8 and 255;val b=p and 255;val level=(r+g+b)/3
            if(g>=b+8 && g>=r*.85 && maxOf(r,g,b)-minOf(r,g,b)>=24 && level>=30)vegetation++
            if(level<25)dark++
            colors[y*w+x]=(r/32)*64+(g/32)*8+b/32
        }
        if(vegetation.toDouble()/(w*h)<.60 || dark.toDouble()/(w*h)>=.12)return false
        val visited=BooleanArray(w*h)
        for(start in colors.indices) {
            if(visited[start])continue
            val queue=mutableListOf(start);var cursor=0;var left=start%w;var right=left;var top=start/w;var bottom=top
            visited[start]=true
            while(cursor<queue.size) {
                val point=queue[cursor++];val x=point%w;val y=point/w
                left=min(left,x);right=max(right,x);top=min(top,y);bottom=max(bottom,y)
                for(next in listOf(if(x>0)point-1 else -1,if(x+1<w)point+1 else -1,if(y>0)point-w else -1,if(y+1<h)point+w else -1)) {
                    if(next>=0 && !visited[next] && colors[next]==colors[start]){visited[next]=true;queue.add(next)}
                }
            }
            val cw=right-left+1;val ch=bottom-top+1
            if(cw>=14 && ch>=4 && queue.size>=max(18,cw*ch/2))return false
        }
        return true
    }

    fun isPrimaryGraphic(width:Int,height:Int,argb:IntArray):Boolean {
        if(width<=0 || height<=0 || argb.size.toLong()!=width.toLong()*height)return true
        var count=0;var left=width;var right=0;var top=height
        for(y in 0 until height)for(x in 0 until width){val pixel=argb[y*width+x];val r=pixel ushr 16 and 255;val g=pixel ushr 8 and 255;val b=pixel and 255
            if(r>=80 && r>1.25*g && r>1.25*b){count++;left=min(left,x);right=max(right,x);top=min(top,y)}
        }
        return count>=.04*width*height && right-left>=.6*width && top<.25*height
    }
    /** Every framed panel must be covered, including a missed bottom clause. */
    fun hasUncoveredAssemblyInk(width:Int,height:Int,argb:IntArray,coveredRows:Set<Int>,components:List<TrafficSignPlateRect>):Boolean {
        if(argb.size!=width*height || components.isEmpty()) return true
        for(rect in components) {
            val trimX=max(3,(rect.width*.10).toInt());val trimY=max(3,(rect.height*.14).toInt())
            val left=max(0,rect.x+trimX);val right=min(width,rect.x+rect.width-trimX)
            val top=max(0,rect.y+trimY);val bottom=min(height,rect.y+rect.height-trimY)
            if(right<=left || bottom<=top) return true
            val levels=(top until bottom).flatMap {y -> (left until right).map {x ->val p=argb[y*width+x];((p ushr 16 and 255)+(p ushr 8 and 255)+(p and 255))/3}}
            val paper=levels.sorted()[(levels.size*.9).toInt()];var run=0
            for(y in top until bottom) {
                val dark=(left until right).count {x ->val p=argb[y*width+x];((p ushr 16 and 255)+(p ushr 8 and 255)+(p and 255))/3 < max(45,(paper*.55).toInt())}
                run=if(y !in coveredRows && dark>=(right-left)*.04 && dark<=(right-left)*.70) run+1 else 0
                if(run>=max(3,(rect.height*.025).roundToInt())) return true
            }
        }
        return false
    }

    fun hasUncoveredInk(width: Int, height: Int, argb: IntArray, coveredRows: Set<Int>): Boolean {
        if (width < 48 || height < 32 || argb.size != width*height) return true
        val levels = argb.map { ((it ushr 16 and 255)+(it ushr 8 and 255)+(it and 255))/3 }
        val paper = levels.sorted()[(levels.size*.9).toInt()]
        val first = coveredRows.minOrNull() ?: return false
        if (first < height*.4) return false
        val left = width/10; val right = width-width/10; val trim = max(4,(height*.18).toInt())
        val end = min(first-3,height/2)
        if (end <= trim) return false
        var run = 0
        for (y in trim until end) {
            val dark = (left until right).count { levels[y*width+it] < max(45,(paper*.55).toInt()) }
            val unexplained = y !in coveredRows && dark >= (right-left)*.05 && dark <= (right-left)*.55
            run = if (unexplained) run+1 else 0
            if (run >= max(3,(height*.03).roundToInt())) return true
        }
        return false
    }

}

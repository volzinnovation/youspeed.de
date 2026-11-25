// Portable inference for the frozen combined model in town-exit-rescue.json.
// The named features follow scripts/town_exit_features.py, including its panel fit.
#include "german_town_exit_rescue.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <numeric>
#include <vector>

namespace {
constexpr int W = YSP_TOWN_EXIT_WIDTH, H = YSP_TOWN_EXIT_HEIGHT;
constexpr int N = W * H;
constexpr int MARGIN_X = 9, MARGIN_Y = 7;
constexpr int INNER_W = W - 2 * MARGIN_X, INNER_H = H - 2 * MARGIN_Y;
struct Pixel { uint8_t r, g, b; };
using Panel = std::array<Pixel, N>;
using Mask = std::array<uint8_t, N>;
using Map = std::array<float, N>;

bool yellow(Pixel p) {
    return p.r >= 45 && p.g >= 35 && p.r >= .94f * p.g && p.g >= .50f * p.r
        && p.g - p.b >= 10 && p.r - p.b >= .15f * p.r;
}

// Bilinear expansion of the cropped panel with a byte rounding step on each axis,
// as in the training-time RGB resampler. Each axis samples from pixel centers.
struct Axis {
    int low, high, highWeight;
};
constexpr int WEIGHT_ONE = 1 << 22;

Axis linearSample(int dest, int targetSize, int start, int size) {
    const double coord = std::clamp((dest + .5) * size / targetSize - .5, 0., double(size - 1));
    const int low = int(coord);
    return {start + low, start + std::min(size - 1, low + 1),
            int(std::lround((coord - low) * WEIGHT_ONE))};
}

uint8_t blendByte(uint8_t a, uint8_t b, int w) {
    return uint8_t((int(a) * (WEIGHT_ONE - w) + int(b) * w + WEIGHT_ONE / 2) >> 22);
}
Pixel blend(Pixel a, Pixel b, int w) {
    return {blendByte(a.r,b.r,w), blendByte(a.g,b.g,w), blendByte(a.b,b.b,w)};
}

void fitPanel(const uint8_t *rgba, Panel &out) {
    Panel input;
    std::array<int, H> rows{};
    std::array<int, W> cols{};
    for (int y = 0; y < H; ++y) for (int x = 0; x < W; ++x) {
        const int i = y * W + x;
        input[i] = {rgba[4*i], rgba[4*i+1], rgba[4*i+2]};
        if (yellow(input[i])) { ++rows[y]; ++cols[x]; }
    }
    int left=W, right=-1, top=H, bottom=-1, nr=0, nc=0;
    for (int x=0; x<W; ++x) if (cols[x] >= .22 * H) {
        left=std::min(left,x); right=x; ++nc;
    }
    for (int y=0; y<H; ++y) if (rows[y] >= .22 * W) {
        top=std::min(top,y); bottom=y; ++nr;
    }
    if (nc < 10 || nr < 10 || (right-left+1 == W && bottom-top+1 == H)) {
        out=input;
        return;
    }
    std::array<Axis,W> xs;
    for (int x=0; x<W; ++x) xs[x]=linearSample(x,W,left,right-left+1);
    for (int y=0; y<H; ++y) {
        const Axis ys=linearSample(y,H,top,bottom-top+1);
        for (int x=0; x<W; ++x) {
            const Axis a=xs[x];
            const Pixel p=blend(input[ys.low*W+a.low], input[ys.low*W+a.high], a.highWeight);
            const Pixel q=blend(input[ys.high*W+a.low], input[ys.high*W+a.high], a.highWeight);
            out[y*W+x]=blend(p,q,ys.highWeight);
        }
    }
}

float median(std::vector<float> &values) {
    const auto mid=values.begin()+values.size()/2;
    std::nth_element(values.begin(),mid,values.end());
    if (values.size()%2) return *mid;
    return .5f * (*mid + *std::max_element(values.begin(),mid));
}

struct Line { float score = 0, continuity = 0; };
using Template = std::array<int,32>;
using Templates = std::array<Template,170>;

Templates makeTemplates(bool rising) {
    Templates result{};
    for (int c=0; c<17; ++c) for (int s=0; s<10; ++s) {
        const double center = .42 + c * ((.82-.42)/16);
        const double slope = (.18 + s * ((.90-.18)/9)) * (rising ? -1 : 1);
        for (int j=0; j<32; ++j) {
            const int x=int(std::nearbyint((.12+j*((.88-.12)/31))*(W-1)));
            const int y=int(std::nearbyint((center+slope*(double(x)/(W-1)-.5))*(H-1)));
            result[10*c+s][j] = (y>=3 && y<H-3) ? y*W+x : -1;
        }
    }
    return result;
}

Line bestLine(const Map &strength, const Templates &templates) {
    Line best;
    for (const auto &line : templates) {
        std::array<float,4> parts{};
        for (int j=0; j<32; ++j) if (line[j]>=0) parts[j/8]+=strength[line[j]]/8.f;
        const float continuity=*std::min_element(parts.begin(),parts.end());
        const float score=.5f*(.25f*std::accumulate(parts.begin(),parts.end(),0.f)+continuity);
        if (score > best.score) best={score,continuity};
    }
    return best;
}

struct Stripe { double score, continuity, orientationMargin; };
Stripe stripeFeatures(const Panel &panel, const Mask &mask) {
    Map redness, local, strength;
    std::vector<float> face;
    face.reserve(N);
    for (int i=0; i<N; ++i) {
        const auto p=panel[i];
        redness[i]=float(p.r-p.g)/(p.r+p.g+28);
        if (mask[i]) face.push_back(redness[i]);
    }
    if (face.empty()) face.assign(redness.begin(),redness.end());
    const float reference=median(face);
    for (int y=0; y<H; ++y) for (int x=0; x<W; ++x) {
        const int i=y*W+x;
        const float flank=.5f*(redness[std::max(0,y-6)*W+x]+redness[std::min(H-1,y+6)*W+x]);
        local[i]=std::sqrt(std::clamp(9.f*(redness[i]-flank),0.f,1.f)
                          *std::clamp(9.f*(redness[i]-reference),0.f,1.f));
    }
    for (int y=0; y<H; ++y) for (int x=0; x<W; ++x) {
        strength[y*W+x]=std::max(local[y*W+x],.85f*std::max(local[std::max(0,y-1)*W+x],local[std::min(H-1,y+1)*W+x]));
    }
    static const Templates rising=makeTemplates(true), falling=makeTemplates(false);
    const auto line=bestLine(strength,rising);
    return {line.score,line.continuity,line.score-bestLine(strength,falling).score};
}

double pointedEdge(const Mask &mask) {
    double strongest=0;
    for (bool reverse : {false,true}) {
        std::vector<float> medians;
        for (int start : {12,32,52}) {
            std::vector<float> edges;
            for (int y=start; y<start+8; ++y) for (int j=0; j<W; ++j) {
                if (mask[y*W+(reverse ? W-1-j : j)]) { edges.push_back(float(j)); break; }
            }
            if (!edges.empty()) medians.push_back(median(edges));
        }
        if (medians.size()==3)
            strongest=std::max(strongest,.5*(medians[0]+medians[2])-medians[1]);
    }
    return strongest/W;
}

using Interior = std::array<uint8_t,INNER_W*INNER_H>;
double componentExtent(const Interior &ink) {
    constexpr int w=INNER_W/2, h=INNER_H/2, stride=w+2;
    std::array<uint8_t,(w+2)*(h+2)> small{};
    for (int y=0; y<h; ++y) for (int x=0; x<w; ++x) {
        const int i=2*y*INNER_W+2*x;
        small[(y+1)*stride+x+1]=(ink[i]+ink[i+1]+ink[i+INNER_W]+ink[i+INNER_W+1]>=2);
    }
    int largest=0;
    std::vector<int> pending;
    for (int i=stride+1; i<(h+1)*stride; ++i) {
        if (!small[i]) continue;
        small[i]=0;
        pending.push_back(i);
        int x0=i%stride, x1=x0, y0=i/stride, y1=y0;
        while (!pending.empty()) {
            const int cur=pending.back();
            pending.pop_back();
            x0=std::min(x0,cur%stride); x1=std::max(x1,cur%stride);
            y0=std::min(y0,cur/stride); y1=std::max(y1,cur/stride);
            for (int n : {cur-stride,cur+stride,cur-1,cur+1}) {
                if (small[n]) { small[n]=0; pending.push_back(n); }
            }
        }
        largest=std::max(largest,(x1-x0+1)*(y1-y0+1));
    }
    return double(largest)/(w*h);
}

using Features = std::array<double,8>;
Features features(const uint8_t *rgba) {
    Panel panel; fitPanel(rgba,panel);
    Mask mask; std::transform(panel.begin(),panel.end(),mask.begin(),yellow);
    const auto stripe=stripeFeatures(panel,mask);
    std::vector<float> greens; greens.reserve(INNER_W*INNER_H);
    for (int y=MARGIN_Y; y<H-MARGIN_Y; ++y) for (int x=MARGIN_X; x<W-MARGIN_X; ++x)
        if (mask[y*W+x]) greens.push_back(panel[y*W+x].g);
    const auto yellowCount=greens.size();
    if (greens.empty()) {
        for (int y=MARGIN_Y; y<H-MARGIN_Y; ++y) for (int x=MARGIN_X; x<W-MARGIN_X; ++x) greens.push_back(panel[y*W+x].g);
    }
    const float faceGreen=median(greens);
    Interior ink{}, pale{};
    std::array<int,INNER_H> rows{};
    int palePatches=0;
    for (int y=0; y<INNER_H; ++y) for (int x=0; x<INNER_W; ++x) {
        const auto p=panel[(y+MARGIN_Y)*W+x+MARGIN_X];
        const int k=y*INNER_W+x, lo=std::min({p.r,p.g,p.b}), hi=std::max({p.r,p.g,p.b});
        ink[k]=p.g < .75f*faceGreen && hi-lo<73 && hi<faceGreen;
        rows[y]+=ink[k];
        pale[k]=lo>=150 && hi-lo<38 && std::abs(p.g-p.b)<30;
        if (x && y && pale[k] && pale[k-1] && pale[k-INNER_W] && pale[k-INNER_W-1]) ++palePatches;
    }
    int strongest=0;
    for (int y=0; y<=INNER_H-10; ++y)
        strongest=std::max(strongest,std::accumulate(rows.begin()+y,rows.begin()+y+10,0));
    return {componentExtent(ink),double(strongest)/std::max(1,std::accumulate(rows.begin(),rows.end(),0)),
            double(palePatches)/((INNER_W-1)*(INNER_H-1)),pointedEdge(mask),double(yellowCount)/(INNER_W*INNER_H),
            stripe.continuity,stripe.orientationMargin,stripe.score};
}
}  // namespace

extern "C" int32_t ysp_german_town_exit_rescue(const uint8_t *rgba) {
    if (!rgba) return 0;
    const auto f=features(rgba);
    // Frozen model, sorted feature order from review/klassifikator/town-exit-rescue.json.
    constexpr Features weights={0.012377701247687506, 0.774254453619705, -0.6000370917886454,
        3.995512201346531, 0.3127649068757599, 2.062571260378366, 2.7933479994388732, 2.609525893075933};
    constexpr double p=0.6558184979800981;
    const double logit=std::inner_product(f.begin(),f.end(),weights.begin(),-2.437796502144707);
    return f.back()>=.12 && logit>std::log(p/(1.-p));
}

#ifdef TOWN_EXIT_VERIFIER_DIAGNOSTICS
extern "C" void ysp_town_exit_features_for_test(const uint8_t *rgba, double *output) {
    const auto f=features(rgba);
    std::copy(f.begin(),f.end(),output);
}
#endif

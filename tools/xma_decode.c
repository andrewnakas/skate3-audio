/*
 * xma_decode - decode a chain of XMA2 chunks through ONE decoder instance.
 *
 * Skate 3 stores each audio context's data as a series of separately framed chunks,
 * one per block (see docs/xma-transcode.md). Decoding each chunk with a fresh decoder
 * loses exactly 64 samples of MDCT overlap at every chunk boundary, because the first
 * frame after a restart needs the previous frame's state. The hardware never pays that
 * cost: it feeds one continuous stream into alternating input buffers, so decoder state
 * carries across chunks.
 *
 * This reproduces that by keeping a single AVCodecContext alive and submitting each
 * chunk as its own packet -- which `ffmpeg` as a subprocess cannot do.
 *
 * Input container (little-endian), produced by tools/eaac_decode.py --dump-chunks:
 *
 *     "XCHK" u32 channels  u32 sample_rate  u32 chunk_count
 *     then chunk_count x { u32 length, length bytes }
 *
 * Output is raw interleaved S16LE.
 *
 * Build: cc -O2 -o xma_decode tools/xma_decode.c $(pkg-config --cflags --libs libavcodec libavutil)
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libavcodec/avcodec.h>
#include <libavutil/channel_layout.h>

static uint32_t rd32(FILE *f) {
    uint8_t b[4];
    if (fread(b, 1, 4, f) != 4) return 0;
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}

static void put16(uint8_t *p, uint16_t v) { p[0] = v & 0xFF; p[1] = v >> 8; }
static void put32(uint8_t *p, uint32_t v) {
    p[0] = v & 0xFF; p[1] = (v >> 8) & 0xFF; p[2] = (v >> 16) & 0xFF; p[3] = v >> 24;
}

/* XMA2WAVEFORMATEX, the 34 bytes libavcodec expects as extradata. */
static void build_extradata(uint8_t *e, int channels, uint32_t samples, uint32_t block, uint16_t blocks) {
    memset(e, 0, 34);
    put16(e + 0, 1);                                   /* NumStreams     */
    put32(e + 2, channels == 1 ? 0x4 : 0x3);           /* ChannelMask    */
    put32(e + 6, samples);                             /* SamplesEncoded */
    put32(e + 10, block);                              /* BytesPerBlock  */
    put32(e + 14, 0);                                  /* PlayBegin      */
    put32(e + 18, samples);                            /* PlayLength     */
    e[30] = 0;                                         /* LoopCount      */
    e[31] = 4;                                         /* EncoderVersion */
    put16(e + 32, blocks);                             /* BlockCount     */
}

static void emit(AVFrame *fr, int channels, FILE *out, long *total) {
    for (int i = 0; i < fr->nb_samples; i++) {
        for (int c = 0; c < channels; c++) {
            float v = 0.f;
            if (fr->format == AV_SAMPLE_FMT_FLTP)
                v = ((const float *)fr->extended_data[c])[i];
            else if (fr->format == AV_SAMPLE_FMT_FLT)
                v = ((const float *)fr->extended_data[0])[i * channels + c];
            if (v > 1.f) v = 1.f;
            if (v < -1.f) v = -1.f;
            int16_t s = (int16_t)lrintf(v * 32767.f);
            uint8_t b[2] = { (uint8_t)(s & 0xFF), (uint8_t)((s >> 8) & 0xFF) };
            fwrite(b, 1, 2, out);
        }
    }
    *total += fr->nb_samples;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: xma_decode <chunks.xchk> <out.pcm>\n");
        return 2;
    }
    FILE *in = fopen(argv[1], "rb");
    if (!in) { perror("open input"); return 1; }
    char magic[4];
    if (fread(magic, 1, 4, in) != 4 || memcmp(magic, "XCHK", 4)) {
        fprintf(stderr, "not an XCHK container\n");
        return 1;
    }
    int channels = (int)rd32(in);
    int rate = (int)rd32(in);
    uint32_t count = rd32(in);

    /* Read every chunk up front so the largest can size block_align. */
    uint8_t **data = calloc(count, sizeof *data);
    uint32_t *lens = calloc(count, sizeof *lens);
    uint32_t biggest = 0;
    for (uint32_t i = 0; i < count; i++) {
        lens[i] = rd32(in);
        data[i] = malloc(lens[i] + AV_INPUT_BUFFER_PADDING_SIZE);
        memset(data[i], 0, lens[i] + AV_INPUT_BUFFER_PADDING_SIZE);
        if (fread(data[i], 1, lens[i], in) != lens[i]) {
            fprintf(stderr, "truncated chunk %u\n", i);
            return 1;
        }
        if (lens[i] > biggest) biggest = lens[i];
    }
    fclose(in);

    const AVCodec *codec = avcodec_find_decoder(AV_CODEC_ID_XMA2);
    if (!codec) { fprintf(stderr, "no xma2 decoder in this libavcodec\n"); return 1; }
    AVCodecContext *ctx = avcodec_alloc_context3(codec);
    ctx->sample_rate = rate;
    av_channel_layout_default(&ctx->ch_layout, channels);
    ctx->block_align = (int)biggest;
    ctx->extradata = av_mallocz(34 + AV_INPUT_BUFFER_PADDING_SIZE);
    ctx->extradata_size = 34;
    build_extradata(ctx->extradata, channels, 0, biggest, (uint16_t)count);

    if (avcodec_open2(ctx, codec, NULL) < 0) { fprintf(stderr, "avcodec_open2 failed\n"); return 1; }

    FILE *out = fopen(argv[2], "wb");
    if (!out) { perror("open output"); return 1; }

    AVPacket *pkt = av_packet_alloc();
    AVFrame *fr = av_frame_alloc();
    long total = 0;
    int failed = 0;
    for (uint32_t i = 0; i < count; i++) {
        pkt->data = data[i];
        pkt->size = (int)lens[i];
        int rc = avcodec_send_packet(ctx, pkt);
        if (rc < 0) { failed++; continue; }
        while (avcodec_receive_frame(ctx, fr) == 0) emit(fr, channels, out, &total);
    }
    avcodec_send_packet(ctx, NULL);            /* flush */
    while (avcodec_receive_frame(ctx, fr) == 0) emit(fr, channels, out, &total);

    fprintf(stderr, "chunks=%u failed=%d channels=%d rate=%d decoded_frames=%ld\n",
            count, failed, channels, rate, total);
    fclose(out);
    av_frame_free(&fr);
    av_packet_free(&pkt);
    avcodec_free_context(&ctx);
    return 0;
}

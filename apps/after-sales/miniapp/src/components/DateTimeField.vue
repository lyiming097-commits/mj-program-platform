<script setup lang="ts">
import { computed } from "vue";

const model = defineModel<string>({ default: "" });

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

const initialNow = new Date();
const defaultDate = `${initialNow.getFullYear()}-${pad(initialNow.getMonth() + 1)}-${pad(initialNow.getDate())}`;
const defaultTime = `${pad(initialNow.getHours())}:${pad(initialNow.getMinutes())}`;
const selectedDate = computed(() => String(model.value || "").slice(0, 10));
const selectedTime = computed(() => String(model.value || "").slice(11, 16));
const pickerDate = computed(() => selectedDate.value || defaultDate);
const pickerTime = computed(() => selectedTime.value || defaultTime);

function updateDate(event: { detail: { value: string } }): void {
  model.value = `${event.detail.value}T${pickerTime.value}:00`;
}

function updateTime(event: { detail: { value: string } }): void {
  model.value = `${pickerDate.value}T${event.detail.value}:00`;
}
</script>

<template>
  <view class="date-time-field">
    <picker class="date-picker" mode="date" :value="pickerDate" @change="updateDate">
      <view class="date-control date-control--date" hover-class="date-control--pressed">{{ selectedDate || "年 / 月 / 日" }}</view>
    </picker>
    <picker class="date-picker" mode="time" :value="pickerTime" @change="updateTime">
      <view class="date-control date-control--time" hover-class="date-control--pressed">{{ selectedTime || "时 : 分" }}</view>
    </picker>
  </view>
</template>

<style scoped>
.date-time-field { display: grid; height: 72rpx; grid-template-columns: minmax(0, 1fr) 180rpx; overflow: hidden; border: 1rpx solid #d8e2ee; border-radius: 14rpx; background: #fff; box-shadow: inset 0 1rpx 0 rgba(255, 255, 255, .9), 0 2rpx 4rpx rgba(15, 23, 42, .04); }
.date-picker { min-width: 0; }
.date-control { display: flex; height: 70rpx; align-items: center; overflow: hidden; padding: 0 20rpx; color: #334155; font-size: 24rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.date-control--time { justify-content: center; border-left: 1rpx solid #dfe6ee; padding: 0 12rpx; }
.date-control--pressed { background: #f5f9ff; color: #155eef; }
</style>

const android = require('@react-native-community/cli-platform-android');
const ios = require('@react-native-community/cli-platform-ios');

module.exports = {
  platforms: {
    android: {
      projectConfig: android.projectConfig,
      dependencyConfig: android.dependencyConfig,
    },
    ios: {
      projectConfig: ios.projectConfig,
      dependencyConfig: ios.dependencyConfig,
    },
  },
};
